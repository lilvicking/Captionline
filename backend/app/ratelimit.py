"""Abuse controls for the unauthenticated and metered endpoints.

Why this exists
---------------
Registration, login, transcription, and the billing session endpoints were all
reachable without any request budget. That is not only a spam problem: Argon2id
at 64 MiB makes an unthrottled login endpoint a cheap way to burn a server's
CPU and RAM, and unthrottled registration is a way to mint unlimited free
transcription time.

Two layers
----------
The cheap layer is an in-process bounded TTL map. It needs no database round
trip, so it absorbs a flood before it can reach Postgres, and it is what every
bucket in the service uses.

The durable layer is a database-backed fixed-window counter, consulted only for
the abuse-critical unauthenticated endpoints (`login`, `register`,
`forgot-password`). It exists because the in-process map is **per replica**: on
a host running N replicas an attacker who reaches all of them gets N times the
limit, every counter resets when a replica is recycled, and a rolling deploy
resets the whole fleet's budget. Those properties are tolerable for
transcription and billing, where the caller is authenticated, and they are not
tolerable where password guessing, free-tier account minting, and mail-provider
flooding all begin.

The durable layer is always the *second* check, never the first. The in-process
pre-filter is kept in front precisely so that a burst of traffic is refused
without opening a database connection for each of them.

Availability over strictness
----------------------------
If the database is unreachable, the table is missing, or the write fails, the
durable check **allows the request and logs**. The reasoning: a rate limiter
that turns a database blip into a 500 on the login page converts a degraded
dependency into a total outage, and a total outage is a worse outcome than a
few requests over budget. The durable counter is an abuse control, not a
security boundary; the control that must not be lost is availability of the
service itself.

Bounded on purpose
------------------
In-process counters are held in an LRU map with a hard ceiling on how many keys
can be tracked, and expired entries are pruned on every call. An earlier attempt
kept a `defaultdict` that was never pruned and keyed on a header the client
fully controlled, so both memory and the limit itself were attacker-controlled.
A limit is an abuse control, not a security boundary, so the worst outcome here
is that a limit is forgotten rather than that the service falls over.

Durable rows are bounded the other way: a row whose window is older than the
longest configured bucket window can never be read again, so an opportunistic
prune deletes it. There is no scheduler and no background thread, so nothing
extra has to be kept running and nothing extra can leak.

Client identity
---------------
The bucket key prefers `request.client.host`, which is the socket peer and
cannot be forged by a header. A forwarded-for header is only consulted when
`TRUST_PROXY_HEADERS` is explicitly enabled, i.e. when a proxy that *overwrites*
that header is known to be in front of the service.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import bindparam, select, text

from .config import Settings, get_settings
from .db.models import RateLimitBucket
from .db.session import get_session_factory

logger = logging.getLogger(__name__)

#: One generic answer for every throttled endpoint. It deliberately says
#: nothing about which limit was hit or what its value is.
RATE_LIMIT_MESSAGE = "Too many requests. Please wait a moment and try again."

#: Bucket name -> the two Settings attributes holding its limit and window.
#: Kept as data so a new endpoint is one line here and one call in its handler.
BUCKET_SETTINGS: dict[str, tuple[str, str]] = {
    "register": ("register_rate_limit", "register_rate_window_seconds"),
    "login": ("login_rate_limit", "login_rate_window_seconds"),
    "transcribe": ("transcribe_rate_limit", "transcribe_rate_window_seconds"),
    "checkout": ("checkout_rate_limit", "checkout_rate_window_seconds"),
    "portal": ("portal_rate_limit", "portal_rate_window_seconds"),
    "change-password": ("change_password_rate_limit", "change_password_rate_window_seconds"),
    "reset-password": ("reset_password_rate_limit", "reset_password_rate_window_seconds"),
    # Its own bucket rather than a share of `change-password`. Deletion is
    # irreversible and is gated on the current password, so a user who mistypes
    # a new password five times must still be able to close their account, and
    # a flood of delete attempts must not be able to spend another control's
    # budget to get there.
    "delete-account": ("delete_account_rate_limit", "delete_account_rate_window_seconds"),
    # The address throttle that used to live in routers/password_reset.py. It
    # keeps its original environment variable names so existing deployments and
    # tests keep working.
    "forgot-password": ("password_reset_ip_limit", "password_reset_ip_window_seconds"),
}

#: Buckets whose count is also kept in the database, so the budget is shared by
#: every replica rather than per replica. Restricted to the unauthenticated
#: endpoints where that difference decides whether a control holds: an
#: authenticated endpoint is already throttled per account by a row in the
#: database, so a per-replica address limit adds nothing there.
DURABLE_BUCKETS = frozenset({"login", "register", "forgot-password"})

_ADDRESS_SCOPE = "addr"
_ACCOUNT_SCOPE = "acct"

#: The smallest number of in-process keys that can hold one request's worth of
#: counting. A check records the address window and, for a bucket that is given
#: an account, the account window, so anything below two evicts a key the same
#: call is still relying on. See the ceiling computation in `check`.
_MIN_TRACKED_KEYS = 2

#: The increment, in one statement. `key` is the primary key, so PostgreSQL
#: serialises conflicting writers on that row: two replicas counting the same
#: address cannot both read a stale count and both slip under the limit, which
#: is exactly the race a read-then-write implementation would have.
#:
#: The syntax is identical on PostgreSQL and on SQLite 3.24+, so it is written
#: once as portable SQL rather than branched on the dialect. `RETURNING` is
#: deliberately *not* used: it needs SQLite 3.35+, and reading the row back in
#: the same transaction is correct on both and costs one cheap primary-key
#: lookup on an index.
#:
#: The `CASE` expressions are what make the window fixed rather than sliding:
#: when the stored window has expired, the same statement that increments the
#: counter also opens a new one, so there is no window where a row is briefly
#: uncounted and two replicas can both claim the first hit.
_DURABLE_UPSERT = text(
    """
    INSERT INTO rate_limit_buckets (key, window_started_at, count)
    VALUES (:key, :now, 1)
    ON CONFLICT (key) DO UPDATE SET
        count = CASE
            WHEN rate_limit_buckets.window_started_at <= :cutoff THEN 1
            ELSE rate_limit_buckets.count + 1
        END,
        window_started_at = CASE
            WHEN rate_limit_buckets.window_started_at <= :cutoff THEN :now
            ELSE rate_limit_buckets.window_started_at
        END
    """
)

_DURABLE_READ = select(RateLimitBucket.count, RateLimitBucket.window_started_at).where(
    RateLimitBucket.key == bindparam("key")
)

_DURABLE_PRUNE = text(
    "DELETE FROM rate_limit_buckets WHERE window_started_at <= :cutoff"
)



@dataclass
class _Bucket:
    """One fixed window. Cheap, and exact enough for abuse control."""

    count: int
    expires_at: float


@dataclass(frozen=True)
class RateLimitDecision:
    """The outcome of a limit check."""

    limited: bool
    retry_after: int
    limit: int


#: Keyed by (bucket, scope, subject) and ordered by last use, so the oldest entry
#: is the cheapest thing to evict when the ceiling is reached.
_windows: "OrderedDict[tuple[str, str, str], _Bucket]" = OrderedDict()
_lock = threading.Lock()

#: Guards `_last_durable_prune` so two threads cannot both decide it is time to
#: sweep. The value is monotonic and per process; the sweep itself is a single
#: idempotent DELETE, so two concurrent sweeps would merely be wasted work, and
#: this keeps that from happening in the first place.
_prune_lock = threading.Lock()
_last_durable_prune = 0.0


def _bucket_settings(bucket: str, settings: Settings | None = None) -> tuple[int, int]:
    """Resolve a bucket name to its (limit, window_seconds) pair."""
    resolved = settings if settings is not None else get_settings()

    attributes = BUCKET_SETTINGS.get(bucket)
    if attributes is None:
        raise KeyError(f"Unknown rate-limit bucket: {bucket!r}")

    limit_attribute, window_attribute = attributes
    return int(getattr(resolved, limit_attribute)), int(getattr(resolved, window_attribute))


def client_address(request: Request, settings: Settings | None = None) -> str:
    """Derive the rate-limit bucket subject for the caller's network address.

    `request.client.host` is the real peer and is preferred. `X-Forwarded-For`
    is attacker controlled unless something upstream rewrites it, so it is only
    read when `TRUST_PROXY_HEADERS` says a trusted proxy is in front. Getting
    this wrong is the difference between a limit that holds and a limit a
    single `curl -H` call defeats.
    """
    resolved = settings if settings is not None else get_settings()

    if resolved.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # The left-most entry is the original client.
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:64]

    if request.client is not None and request.client.host:
        return request.client.host[:64]

    return "unknown"


def account_key(raw: str) -> str:
    """Derive a stable, non-reversible bucket subject for an account.

    The limiter never needs to know *which* account it is counting, only whether
    two requests name the same one, so the value is hashed. That keeps email
    addresses out of process memory even for the short lifetime of a window.
    """
    normalised = (raw or "").strip().lower()
    if not normalised:
        return ""

    return hashlib.sha256(normalised.encode("utf-8", "replace")).hexdigest()[:32]


def _prune_expired(now: float) -> None:
    """Drop every window that has aged out. Called on each check."""
    for key in [key for key, window in _windows.items() if window.expires_at <= now]:
        del _windows[key]


def _record(
    key: tuple[str, str, str],
    *,
    limit: int,
    window_seconds: int,
    now: float,
    ceiling: int,
) -> RateLimitDecision:
    """Count one hit against a key, creating or recycling its window."""
    window = _windows.get(key)

    if window is None or window.expires_at <= now:
        window = _Bucket(count=0, expires_at=now + window_seconds)
        _windows[key] = window
    else:
        _windows.move_to_end(key)

    window.count += 1

    if len(_windows) > ceiling:
        # Bounded memory. The map is LRU-ordered by the move_to_end above, so
        # the first key is the least recently used one.
        while len(_windows) > ceiling:
            _windows.popitem(last=False)

    if window.count > limit:
        return RateLimitDecision(
            limited=True, retry_after=max(1, int(window.expires_at - now)), limit=limit
        )

    return RateLimitDecision(limited=False, retry_after=0, limit=limit)


def longest_window_seconds(settings: Settings | None = None) -> int:
    """The longest window any configured bucket uses.

    The durable prune uses this as its retention horizon: a window that has been
    open for longer than the longest configured window can no longer be consulted
    by any bucket, so the row is dead weight. Deriving the horizon from the
    bucket settings rather than from a separate setting means an operator who
    lengthens a window cannot accidentally leave rows behind forever.
    """
    resolved = settings if settings is not None else get_settings()

    return max(
        (int(getattr(resolved, window_attribute)) for _, window_attribute in BUCKET_SETTINGS.values()),
        default=0,
    )


def _durable_key(bucket: str, scope: str, subject: str) -> str:
    """Compose the primary key of a durable window.

    The bucket name and scope are included so one subject can hold an
    independent budget per control: five failed logins and five delete attempts
    are different events and must not share a counter.
    """
    return f"{bucket}:{scope}:{subject}"


def _prune_durable(session, cutoff: datetime) -> None:
    """Delete every durable window that opened before `cutoff`.

    Opportunistic and best effort: it runs at most once per
    `RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS` per process, from a request that
    is already writing to this table. There is deliberately no scheduler and no
    background thread, so there is nothing extra to deploy, supervise, or leak.
    """
    session.execute(_DURABLE_PRUNE, {"cutoff": cutoff})
    session.commit()


def _maybe_prune_durable(settings: Settings) -> None:
    global _last_durable_prune

    interval = max(0, int(settings.rate_limit_durable_prune_interval_seconds))
    monotonic_now = time.monotonic()

    with _prune_lock:
        if monotonic_now - _last_durable_prune < interval:
            return
        _last_durable_prune = monotonic_now

    horizon = max(0, longest_window_seconds(settings))
    if horizon == 0:
        return

    session = _durable_session(settings)
    if session is None:
        return

    try:
        _prune_durable(session, datetime.now(timezone.utc) - timedelta(seconds=horizon))
    except Exception as exc:
        # Sweeping is housekeeping. Failing to sweep must never affect a
        # request, so the transaction is abandoned and the sweep retried on the
        # next interval.
        session.rollback()
        logger.warning("Durable rate-limit prune skipped: %s", type(exc).__name__)
    finally:
        session.close()


def _durable_session(settings: Settings):
    """Open a short-lived session for one durable counter operation.

    Deliberately *not* the request's session. The counter has to survive a
    rolled-back request: otherwise an attacker who makes the handler fail after
    the limiter runs gets the hit refunded, and the limit stops limiting. An
    independent session also means a failure here cannot poison the transaction
    that is doing the real work.
    """
    if not settings.rate_limit_durable_enabled:
        return None

    if not settings.database_url:
        # No database configured means transcription-only, not an outage. There
        # is nothing to be strict about, so the in-process limiter is the whole
        # control and nothing is logged on every request.
        return None

    factory = get_session_factory()
    if factory is None:
        return None

    return factory()


def _durable_decision(
    bucket: str,
    scope: str,
    subject: str,
    *,
    limit: int,
    window_seconds: int,
    settings: Settings,
) -> RateLimitDecision:
    """Count one hit in the shared table and report whether the caller is over.

    Returns "not limited" on **any** failure to reach or update the database.
    That is the deliberate trade: a limiter that turns a database blip into a
    500 on the login page replaces a degraded dependency with an outage, and an
    outage is the worse failure. The failure is logged so an operator can see
    that the shared budget is not being enforced, which is a materially
    different situation from it silently not existing.
    """
    allowed = RateLimitDecision(limited=False, retry_after=0, limit=limit)

    session = _durable_session(settings)
    if session is None:
        return allowed

    now = datetime.now(timezone.utc)
    key = _durable_key(bucket, scope, subject)

    try:
        session.execute(
            _DURABLE_UPSERT,
            {"key": key, "now": now, "cutoff": now - timedelta(seconds=window_seconds)},
        )
        # Read back in the same transaction so the value observed is the one
        # this statement wrote, not a concurrent replica's.
        row = session.execute(_DURABLE_READ, {"key": key}).one_or_none()
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning(
            "Durable rate limit for %s could not be enforced (%s); allowing the "
            "request. Availability is preferred over strictness here.",
            bucket,
            type(exc).__name__,
        )
        return allowed
    finally:
        session.close()

    if row is None:  # pragma: no cover - the upsert above always leaves a row
        return allowed

    count, window_started_at = int(row[0]), row[1]

    # SQLite hands back a naive datetime because it stores no zone. Everything
    # is written in UTC, so a naive value is UTC by construction.
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=timezone.utc)

    retry_after = max(
        1, int((window_started_at + timedelta(seconds=window_seconds) - now).total_seconds())
    )

    return RateLimitDecision(limited=count > limit, retry_after=retry_after, limit=limit)


def _durable_consume(
    bucket: str,
    *,
    subjects: list[tuple[str, str]],
    limit: int,
    window_seconds: int,
    settings: Settings,
) -> RateLimitDecision:
    """Count this request against every durable subject it touches.

    Both dimensions are counted, as in the in-process layer, because either one
    alone is trivially evaded. The address is evaluated first and the account
    only when the address passed, so a caller who is already over budget on
    their address does not also spend a write on their account row.
    """
    decision = RateLimitDecision(limited=False, retry_after=0, limit=limit)

    for index, (scope, subject) in enumerate(subjects):
        candidate = _durable_decision(
            bucket,
            scope,
            subject,
            limit=limit,
            window_seconds=window_seconds,
            settings=settings,
        )

        if not candidate.limited:
            if index == 0:
                decision = candidate
            continue

        if decision.limited:
            decision = RateLimitDecision(
                limited=True,
                retry_after=max(decision.retry_after, candidate.retry_after),
                limit=limit,
            )
        else:
            decision = candidate

    _maybe_prune_durable(settings)

    return decision


def check(
    bucket: str,
    request: Request,
    *,
    account: str | None = None,
    settings: Settings | None = None,
) -> RateLimitDecision:
    """Count this request against a bucket without changing the response shape.

    The same limit is applied to the client address and, when `account` is
    given, to that account. Two dimensions are needed because either one alone
    is trivially evaded: an attacker with many addresses defeats a per-address
    limit, and an attacker with one account behind many addresses defeats a
    per-account limit.

    For the buckets in `DURABLE_BUCKETS` the same subjects are also counted in
    the shared table, so the budget survives a replica restart and is not
    multiplied by the number of replicas. That second check only runs once the
    cheap in-process one has passed, which is what keeps a flood off the
    database.

    A limit or window of 0 disables the bucket, which is the documented way to
    turn a control off without a code change.
    """
    resolved = settings if settings is not None else get_settings()
    limit, window_seconds = _bucket_settings(bucket, resolved)

    if limit <= 0 or window_seconds <= 0:
        return RateLimitDecision(limited=False, retry_after=0, limit=limit)

    # A single check records up to two keys: the address window and, when an
    # account is supplied, the account window. A ceiling below that is not a
    # tighter memory bound, it is an absent one: the two keys evict each other on
    # every call, so each is written, counted to 1, and thrown away again. Both
    # counts then sit at 1 forever and the limit never trips, which turns every
    # bucket in the service into a no-op. `RATE_LIMIT_MAX_KEYS=0` and `=1` are
    # therefore floors of nonsense rather than usable settings, and are raised
    # to the smallest value that can actually hold a request's two dimensions.
    #
    # This changes no limit, window, or bucket. It only stops a memory bound from
    # silently voiding the abuse limits that are already configured.
    ceiling = max(_MIN_TRACKED_KEYS, resolved.rate_limit_max_keys)
    address = client_address(request, resolved)
    subject = account_key(account) if account else None

    now = time.monotonic()
    decision = RateLimitDecision(limited=False, retry_after=0, limit=limit)

    with _lock:
        _prune_expired(now)

        address_decision = _record(
            (bucket, _ADDRESS_SCOPE, address),
            limit=limit,
            window_seconds=window_seconds,
            now=now,
            ceiling=ceiling,
        )
        decision = address_decision

        if subject:
            account_decision = _record(
                (bucket, _ACCOUNT_SCOPE, subject),
                limit=limit,
                window_seconds=window_seconds,
                now=now,
                ceiling=ceiling,
            )
            if account_decision.limited and not decision.limited:
                decision = account_decision
            elif account_decision.limited:
                decision = RateLimitDecision(
                    limited=True,
                    retry_after=max(decision.retry_after, account_decision.retry_after),
                    limit=limit,
                )

    if decision.limited:
        logger.info("Rate limit reached for %s", bucket)
        return decision

    if bucket in DURABLE_BUCKETS:
        subjects = [(_ADDRESS_SCOPE, address)]
        if subject:
            subjects.append((_ACCOUNT_SCOPE, subject))

        decision = _durable_consume(
            bucket,
            subjects=subjects,
            limit=limit,
            window_seconds=window_seconds,
            settings=resolved,
        )

        if decision.limited:
            logger.info("Shared rate limit reached for %s", bucket)

    return decision



def allow(
    bucket: str,
    request: Request,
    *,
    account: str | None = None,
    settings: Settings | None = None,
) -> bool:
    """Whether the request may proceed. Never raises, never changes the body.

    Used by `POST /api/auth/forgot-password`, which must answer with its generic
    message whether or not the caller was throttled: a 429 there would reveal
    that the address is under observation, which is itself an enumeration
    signal.
    """
    return not check(bucket, request, account=account, settings=settings).limited


def enforce(
    bucket: str,
    request: Request,
    *,
    account: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Reject the request with 429 and a generic message when it is over budget."""
    decision = check(bucket, request, account=account, settings=settings)

    if not decision.limited:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMIT_MESSAGE,
        headers={"Retry-After": str(decision.retry_after)},
    )


def tracked_key_count() -> int:
    """How many in-process buckets are currently held. Asserts the memory bound."""
    with _lock:
        return len(_windows)


def reset_rate_limits() -> None:
    """Clear every in-process counter. Used by tests and at process startup.

    The durable table is deliberately *not* cleared here. This runs from
    `app.main.lifespan`, so wiping the shared table at startup would let any one
    replica restarting reset the whole fleet's budget, which is the property the
    durable layer exists to remove. `reset_durable_rate_limits` is the separate,
    explicitly destructive helper, and only tests call it.
    """
    with _lock:
        _windows.clear()


def durable_tracked_key_count(settings: Settings | None = None) -> int:
    """How many shared windows are stored. Used to assert the prune works."""
    resolved = settings if settings is not None else get_settings()
    session = _durable_session(resolved)

    if session is None:
        return 0

    try:
        count = session.execute(
            text("SELECT COUNT(*) FROM rate_limit_buckets")
        ).scalar_one()
    except Exception as exc:
        session.rollback()
        logger.warning(
            "Durable rate-limit count unavailable: %s", type(exc).__name__
        )
        return 0
    finally:
        session.close()

    return int(count or 0)


def reset_durable_rate_limits(settings: Settings | None = None) -> None:
    """Empty the shared table. Destructive, and for tests only.

    Never called from application code: see `reset_rate_limits` for why a
    startup clear would undo the control.
    """
    resolved = settings if settings is not None else get_settings()
    session = _durable_session(resolved)

    if session is None:
        return

    try:
        session.execute(text("DELETE FROM rate_limit_buckets"))
        session.commit()
    except Exception as exc:  # pragma: no cover - tests fail loudly on this
        session.rollback()
        logger.warning(
            "Durable rate limits could not be reset: %s", type(exc).__name__
        )
    finally:
        session.close()

    global _last_durable_prune
    with _prune_lock:
        _last_durable_prune = 0.0


__all__ = [
    "BUCKET_SETTINGS",
    "DURABLE_BUCKETS",
    "RATE_LIMIT_MESSAGE",
    "RateLimitDecision",
    "account_key",
    "allow",
    "check",
    "client_address",
    "durable_tracked_key_count",
    "enforce",
    "longest_window_seconds",
    "reset_durable_rate_limits",
    "reset_rate_limits",
    "tracked_key_count",
]
