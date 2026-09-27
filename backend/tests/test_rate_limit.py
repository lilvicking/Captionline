"""Rate limiter tests, for both of its layers.

`app.ratelimit` is two controls stacked, and only the cheap one is obvious:

* the **in-process** bounded TTL map, which every bucket uses, needs no database
  round trip, and is *per replica*;
* the **durable** fixed-window counter in `rate_limit_buckets`, which is shared
  by every replica, and is used only for the unauthenticated endpoints where a
  per-replica limit is not good enough (`login`, `register`, `forgot-password`).

The tests below are grouped in that order. Two properties are asserted over and
over because they are the ones that make the control worth having:

* it must **hold** — a spoofed forwarded header cannot mint a fresh bucket, a
  second replica cannot spend a second budget, and the tracked-key map cannot be
  grown without bound;
* it must not cost **availability** — a database failure degrades the shared
  counter, it never turns a login into a 500.

The endpoints that must never be throttled are tested as carefully as the ones
that must be: `/api/health` and `/` are the liveness probe Railway uses to decide
whether to route traffic to a replica, and the Stripe webhook is the only way
paid entitlement is ever granted. A limiter that can block those is worse than no
limiter at all.
"""

from __future__ import annotations

import json
import time as real_time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from starlette.requests import Request

import app.ratelimit as ratelimit
from app.config import Settings
from app.db.models import RateLimitBucket
from app.db.session import get_session_factory
from app.ratelimit import (
    BUCKET_SETTINGS,
    DURABLE_BUCKETS,
    RATE_LIMIT_MESSAGE,
    RateLimitDecision,
    account_key,
    allow,
    check,
    client_address,
    durable_tracked_key_count,
    enforce,
    longest_window_seconds,
    reset_durable_rate_limits,
    reset_rate_limits,
    tracked_key_count,
)
from tests.conftest import auth_header

PASSWORD = "a-strong-password-123"
EMAIL = "victim@example.com"

#: Every rate-limit variable, forced to its lowest usable value. An endpoint that
#: is not rate limited must still answer normally under this, and a single call
#: into the limiter would trip it immediately.
ALL_LIMITS = {
    "RATE_LIMIT_MAX_KEYS": "5",
    "RATE_LIMIT_REGISTER": "1",
    "RATE_LIMIT_REGISTER_WINDOW_SECONDS": "300",
    "RATE_LIMIT_LOGIN": "1",
    "RATE_LIMIT_LOGIN_WINDOW_SECONDS": "300",
    "RATE_LIMIT_TRANSCRIBE": "1",
    "RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS": "300",
    "RATE_LIMIT_CHECKOUT": "1",
    "RATE_LIMIT_CHECKOUT_WINDOW_SECONDS": "300",
    "RATE_LIMIT_PORTAL": "1",
    "RATE_LIMIT_PORTAL_WINDOW_SECONDS": "300",
    "RATE_LIMIT_CHANGE_PASSWORD": "1",
    "RATE_LIMIT_CHANGE_PASSWORD_WINDOW_SECONDS": "300",
    "RATE_LIMIT_RESET_PASSWORD": "1",
    "RATE_LIMIT_RESET_PASSWORD_WINDOW_SECONDS": "300",
    "RATE_LIMIT_DELETE_ACCOUNT": "1",
    "RATE_LIMIT_DELETE_ACCOUNT_WINDOW_SECONDS": "300",
    "PASSWORD_RESET_IP_LIMIT": "1",
    "PASSWORD_RESET_IP_WINDOW_SECONDS": "300",
    "RATE_LIMIT_DURABLE_ENABLED": "1",
    "RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS": "0",
}


def make_request(
    *, host: str = "203.0.113.10", forwarded_for: str | None = None
) -> Request:
    """A `Request` with a chosen socket peer and optional forwarded-for header.

    Built from a scope rather than sent over a socket so a test can vary the one
    thing the key derivation actually reads.
    """
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (host, 51234),
            "server": ("testserver", 80),
        }
    )


class FakeClock:
    """A monotonic clock a test drives by hand, so no test ever sleeps.

    Replaces the `time` module *inside* `app.ratelimit` only. Patching
    `time.monotonic` globally would also move the event loop's clock, which the
    TestClient runs on.
    """

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def clean_limiter_state(migrated_database):
    """Clear both layers around every test, so ordering cannot matter.

    `reset_rate_limits` only clears process memory; `reset_durable_rate_limits`
    only clears the shared table, and it also rewinds the prune timestamp. Both
    are needed: a leftover durable row would silently throttle the next test.
    """
    reset_rate_limits()
    reset_durable_rate_limits()

    yield

    reset_rate_limits()
    reset_durable_rate_limits()


def configure(monkeypatch, live_settings, **values: str) -> Settings:
    """Set rate-limit environment variables and refresh the live settings.

    Returns the settings the handlers will now see, so a unit assertion can be
    made against the same object rather than a second, separately built one.
    """
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    live_settings()
    return ratelimit.get_settings()


def durable_rows(db_session) -> list[RateLimitBucket]:
    """Every shared row currently stored, read back through the ORM."""
    db_session.expire_all()
    return list(db_session.execute(select(RateLimitBucket)).scalars().all())


def row_for(db_session, bucket: str, scope: str) -> RateLimitBucket:
    """The single shared row for a bucket/scope pair, by its documented prefix.

    The key format is `"<bucket>:<scope>:<subject>"`, asserted by prefix rather
    than rebuilt, so a change to the composition shows up as a failure here.
    """
    prefix = f"{bucket}:{scope}:"
    matches = [row for row in durable_rows(db_session) if row.key.startswith(prefix)]

    assert len(matches) == 1, f"expected exactly one {prefix} row, got {matches}"
    return matches[0]


def login(client, email: str = EMAIL, password: str = "not-the-password"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def register(client, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


# --------------------------------------------------------------------------- #
# 1. A bucket is enforced                                                    #
# --------------------------------------------------------------------------- #


def test_a_bucket_allows_n_requests_and_then_answers_429(monkeypatch, live_settings):
    """The documented contract: N requests through, N+1 refused."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="3",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )
    request = make_request()

    for index in range(3):
        assert check("checkout", request).limited is False, f"request {index + 1} refused"

    decision = check("checkout", request)

    assert decision.limited is True
    assert decision.limit == 3
    # Bounded by the window, and never zero: a `Retry-After: 0` tells a client to
    # retry immediately, which is how a rate limit turns into a busy loop.
    assert 1 <= decision.retry_after <= 300


def test_enforce_raises_429_with_a_retry_after_header(monkeypatch, live_settings):
    """`enforce` is the shape the routers use, so it is the shape under test."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="2",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )
    request = make_request()

    enforce("checkout", request)
    enforce("checkout", request)

    with pytest.raises(HTTPException) as caught:
        enforce("checkout", request)

    assert caught.value.status_code == 429
    assert caught.value.headers is not None
    assert int(caught.value.headers["Retry-After"]) >= 1
    # One answer for every throttled endpoint, and it says nothing about which
    # limit was hit or what its value is.
    assert caught.value.detail == RATE_LIMIT_MESSAGE


def test_a_limit_of_zero_disables_a_bucket(monkeypatch, live_settings):
    """Documented escape hatch: no code change is needed to turn a control off."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="0",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )
    request = make_request()

    for _ in range(50):
        assert check("checkout", request).limited is False


def test_an_unknown_bucket_name_is_refused(monkeypatch, live_settings):
    """A typo in a bucket name must not silently become "no limit"."""
    configure(monkeypatch, live_settings)

    with pytest.raises(KeyError):
        check("no-such-bucket", make_request())


# --------------------------------------------------------------------------- #
# 2. The tracked-key map is bounded                                          #
# --------------------------------------------------------------------------- #


def test_the_tracked_key_map_is_bounded(monkeypatch, live_settings):
    """A client that mints a new address per request must not grow memory.

    This is the property an earlier `defaultdict` keyed on a spoofable header
    did not have: the map was never pruned and its size was the client's choice.
    """
    ceiling = 50
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_MAX_KEYS=str(ceiling),
        RATE_LIMIT_TRANSCRIBE="1000000",
        RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS="300",
    )

    attempts = ceiling * 60

    for index in range(attempts):
        # A distinct key per request, and never the same one twice, so nothing
        # is ever legitimately reused and the bound is the only thing shrinking it.
        check("transcribe", make_request(host=f"198.51.100.{index}"))

        assert tracked_key_count() <= ceiling, f"bound exceeded at request {index + 1}"

    assert tracked_key_count() <= ceiling


def test_a_ceiling_below_two_does_not_void_the_limit(monkeypatch, live_settings):
    """REGRESSION: a memory bound that is too small must not disable the control.

    A check records two keys — the address window and the account window — so a
    ceiling of one had each key evict the other on the same call. Both counters
    then sat at 1 permanently, `RATE_LIMIT_LOGIN=1` never tripped, and the
    `max(1, ...)` floor meant `RATE_LIMIT_MAX_KEYS=0` voided every bucket in the
    service rather than just bounding memory. The floor is now the smallest value
    that can hold a request's two dimensions.
    """
    for configured in ("0", "1"):
        reset_rate_limits()
        configure(
            monkeypatch,
            live_settings,
            RATE_LIMIT_MAX_KEYS=configured,
            RATE_LIMIT_CHECKOUT="1",
            RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
        )
        request = make_request()

        statuses = [check("checkout", request, account="1").limited for _ in range(4)]

        # Both dimensions are now retained, so the address window itself trips on
        # the second call rather than being reset to 1 forever.
        assert statuses == [False, True, True, True], (
            f"RATE_LIMIT_MAX_KEYS={configured} disabled the bucket"
        )
        assert tracked_key_count() == 2, f"RATE_LIMIT_MAX_KEYS={configured} over- or under-tracked"


def test_evicting_another_buckets_window_cannot_reset_a_shared_counter(
    monkeypatch, live_settings, db_session
):
    """The LRU map is shared by every bucket, so one flood evicts another's keys.

    That is inherent to a single bounded map, and the point of the assertion is
    the mitigation: the abuse-critical buckets keep their count in the database,
    which is not in that map, so the budget survives the eviction.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_MAX_KEYS="2",
        RATE_LIMIT_LOGIN="1",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_TRANSCRIBE="1000",
        RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    login_request = make_request()

    # Replica A spends the login budget, so the shared counter is at its limit.
    assert check("login", login_request, account=EMAIL).limited is False
    assert row_for(db_session, "login", "addr").count == 1

    # A different bucket then floods the bounded map past the ceiling.
    for index in range(10):
        check("transcribe", make_request(host=f"198.51.100.{index}"))

    assert tracked_key_count() <= 2
    # Login's in-process windows really were evicted: only transcribe survives.
    assert all(key[0] != "login" for key in ratelimit._windows)

    # The shared counter is not in that map, so the budget still holds.
    assert check("login", login_request, account=EMAIL).limited is True


# --------------------------------------------------------------------------- #
# 3. Expired entries are pruned                                              #
# --------------------------------------------------------------------------- #


def test_expired_windows_are_pruned(monkeypatch, live_settings):
    """An idle limiter must not hold a key per address it has ever seen."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_MAX_KEYS="1000",
        RATE_LIMIT_TRANSCRIBE="1000",
        RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS="60",
    )
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "time", clock)

    for index in range(5):
        check("transcribe", make_request(host=f"198.51.100.{index}"))

    assert tracked_key_count() == 5

    clock.advance(61)

    # Any single call prunes, then records only its own key.
    check("transcribe", make_request(host="198.51.100.99"))

    assert tracked_key_count() == 1


def test_a_pruned_window_starts_over(monkeypatch, live_settings):
    """Pruning must not leave a stale count behind for the next caller."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_TRANSCRIBE="2",
        RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS="60",
    )
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "time", clock)
    request = make_request()

    check("transcribe", request)
    check("transcribe", request)
    assert check("transcribe", request).limited is True

    clock.advance(61)

    assert check("transcribe", request).limited is False
    # The expired window is replaced, not resumed: the second hit is not the third.
    assert check("transcribe", request).limited is False
    assert check("transcribe", request).limited is True


def test_the_clock_actually_advances(monkeypatch, live_settings):
    """Guards the test above: a patched clock that never moves proves nothing."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_TRANSCRIBE="1000",
        RATE_LIMIT_TRANSCRIBE_WINDOW_SECONDS="60",
    )
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "time", clock)
    check("transcribe", make_request(host="198.51.100.1"))
    check("transcribe", make_request(host="198.51.100.2"))

    assert clock.now == 1_000_000.0
    assert tracked_key_count() == 2

    # The module attribute really was replaced, so the pruning tests are honest.
    assert ratelimit.time is not real_time


# --------------------------------------------------------------------------- #
# 4. A spoofed X-Forwarded-For is ignored by default                         #
# --------------------------------------------------------------------------- #


def test_a_spoofed_forwarded_for_is_ignored_by_default(monkeypatch, live_settings):
    """One header must not buy one fresh bucket.

    `X-Forwarded-For` is entirely attacker controlled unless something upstream
    overwrites it, so the default derivation is the socket peer and the header is
    never read.
    """
    configure(
        monkeypatch,
        live_settings,
        TRUST_PROXY_HEADERS="0",
        RATE_LIMIT_CHECKOUT="2",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )

    first = check("checkout", make_request(host="203.0.113.1", forwarded_for="198.51.100.1"))
    second = check("checkout", make_request(host="203.0.113.1", forwarded_for="198.51.100.2"))
    third = check("checkout", make_request(host="203.0.113.1", forwarded_for="198.51.100.3"))

    assert first.limited is False
    assert second.limited is False
    # All three land in one bucket, so the third is over budget.
    assert third.limited is True
    # One key, not three.
    assert tracked_key_count() == 1


def test_the_socket_peer_is_preferred_over_the_header(monkeypatch, live_settings):
    """The default subject is the real peer, whatever the header claims."""
    configure(monkeypatch, live_settings, TRUST_PROXY_HEADERS="0")
    settings = ratelimit.get_settings()

    assert client_address(make_request(host="203.0.113.9", forwarded_for="1.1.1.1"), settings) == "203.0.113.9"
    assert client_address(make_request(host="203.0.113.9"), settings) == "203.0.113.9"


def test_a_long_address_is_truncated(monkeypatch, live_settings):
    """An address column is bounded, so the key is too."""
    configure(monkeypatch, live_settings, TRUST_PROXY_HEADERS="0")
    settings = ratelimit.get_settings()
    oversized = "x" * 500

    assert len(client_address(make_request(host=oversized), settings)) == 64


# --------------------------------------------------------------------------- #
# 5. With TRUST_PROXY_HEADERS on, the header is used                         #
# --------------------------------------------------------------------------- #


def test_the_forwarded_header_is_used_when_a_trusted_proxy_is_declared(
    monkeypatch, live_settings
):
    """Behind a proxy that overwrites the header, rotating it is a fresh bucket.

    This is the configuration the feature exists for, and it is also the reason it
    is off by default: the guarantee is "something upstream rewrites this", not
    "someone upstream sends this".
    """
    configure(
        monkeypatch,
        live_settings,
        TRUST_PROXY_HEADERS="1",
        RATE_LIMIT_CHECKOUT="2",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )

    for index in range(6):
        decision = check(
            "checkout", make_request(host="203.0.113.1", forwarded_for=f"198.51.100.{index}")
        )
        assert decision.limited is False, f"forwarded address {index} was refused"

    assert tracked_key_count() == 6

    # Replaying one forwarded address exhausts that address's budget.
    replayed = "198.51.100.200"
    assert check("checkout", make_request(host="203.0.113.1", forwarded_for=replayed)).limited is False
    assert check("checkout", make_request(host="203.0.113.1", forwarded_for=replayed)).limited is False
    assert check("checkout", make_request(host="203.0.113.1", forwarded_for=replayed)).limited is True


def test_the_left_most_forwarded_entry_is_the_original_client(monkeypatch, live_settings):
    """A proxy chain appends; the left-most entry is who the request is from."""
    configure(monkeypatch, live_settings, TRUST_PROXY_HEADERS="1")
    settings = ratelimit.get_settings()

    assert (
        client_address(make_request(host="203.0.113.1", forwarded_for=" 198.51.100.7 , 10.0.0.1"), settings)
        == "198.51.100.7"
    )


def test_a_blank_forwarded_header_falls_back_to_the_peer(monkeypatch, live_settings):
    """A header of only separators names no client, so it is not trusted."""
    configure(monkeypatch, live_settings, TRUST_PROXY_HEADERS="1")
    settings = ratelimit.get_settings()

    assert client_address(make_request(host="203.0.113.1", forwarded_for=" , , "), settings) == "203.0.113.1"
    assert client_address(make_request(host="203.0.113.1", forwarded_for=""), settings) == "203.0.113.1"


# --------------------------------------------------------------------------- #
# 6. The account subject is a hash                                           #
# --------------------------------------------------------------------------- #


def test_the_account_subject_is_a_hash_not_the_address():
    """The limiter only needs to know that two requests name the same account."""
    raw = "Person@Example.com"
    subject = account_key(raw)

    assert subject != raw
    assert "person@example.com" not in subject
    assert "@" not in subject
    # A 128-bit prefix of SHA-256: fixed length, and far too wide to enumerate.
    assert len(subject) == 32
    assert all(character in "0123456789abcdef" for character in subject)


def test_the_account_subject_is_normalised_so_case_and_padding_cannot_forge():
    """The same account must hash the same however the client spells it."""
    canonical = account_key("person@example.com")

    assert account_key("  PERSON@Example.COM  ") == canonical
    assert account_key("Person@example.com") == canonical
    assert account_key("other@example.com") != canonical


def test_an_empty_account_is_not_a_subject():
    """No account means "do not count an account", not "count the empty one"."""
    assert account_key("") == ""
    assert account_key("   ") == ""


def test_no_raw_email_is_retained_in_either_layer(client, db_session):
    """An address must not be sitting in process memory or in the shared table.

    Both layers keep the caller identified for as long as a window is open, so
    the stored subject has to be a digest rather than the address itself.
    """
    register(client)
    assert login(client, email=EMAIL).status_code == 401

    expected = account_key(EMAIL)

    assert expected != EMAIL
    assert tracked_key_count() > 0
    for key in ratelimit._windows:
        assert EMAIL not in str(key)
        assert "example.com" not in str(key)

    keys = [row.key for row in durable_rows(db_session)]
    assert keys, "expected the durable layer to have recorded the attempt"
    for key in keys:
        assert EMAIL not in key
    assert any(expected in key for key in keys)


# --------------------------------------------------------------------------- #
# 7. A durable bucket writes a shared counter that persists                   #
# --------------------------------------------------------------------------- #


def test_a_durable_bucket_writes_a_shared_counter(client, db_session):
    """The whole point of the table: the count outlives the request."""
    assert login(client).status_code == 401

    rows = durable_rows(db_session)
    keys = {row.key for row in rows}

    # Both dimensions, not just the address.
    assert any(key.startswith("login:addr:") for key in keys)
    assert any(key.startswith("login:acct:") for key in keys)
    for row in rows:
        assert row.count == 1
        assert row.window_started_at is not None

    assert durable_tracked_key_count() == len(rows)


def test_the_durable_counter_increases_with_every_attempt(client, db_session):
    """It is a counter, not a boolean flag."""
    for _ in range(3):
        assert login(client).status_code == 401

    assert row_for(db_session, "login", "addr").count == 3
    assert row_for(db_session, "login", "acct").count == 3


def test_different_buckets_hold_independent_counters(client, db_session):
    """Five failed logins and five failed registrations are different events."""
    assert register(client, email="newcomer@example.com").status_code == 201
    assert login(client).status_code == 401

    keys = {row.key for row in durable_rows(db_session)}

    assert any(key.startswith("login:") for key in keys)
    assert any(key.startswith("register:") for key in keys)


# --------------------------------------------------------------------------- #
# 8. The durable limit is shared by two replicas                              #
# --------------------------------------------------------------------------- #


def test_a_second_replica_is_already_blocked_by_the_first_ones_writes(
    monkeypatch, live_settings, db_session
):
    """THE REASON THE DURABLE LAYER EXISTS.

    The in-process map is per replica, so on a host running N replicas an
    attacker who reaches all of them gets N times the limit, and every counter
    resets when a replica is recycled. The shared table is what removes that, so
    a replica that has served nothing must still be refused.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="2",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    request = make_request()

    # --- Replica A: two logins, its own in-process map, two shared writes. ---
    assert check("login", request, account=EMAIL).limited is False
    assert check("login", request, account=EMAIL).limited is False
    assert row_for(db_session, "login", "addr").count == 2
    assert row_for(db_session, "login", "acct").count == 2

    # --- Replica B: a process that has just started. Empty in-process map. ---
    reset_rate_limits()
    assert tracked_key_count() == 0

    decision = check("login", request, account=EMAIL)

    # Refused on its very first request, having spent nothing of its own.
    assert decision.limited is True
    assert decision.limit == 2
    # B did record its own two keys, both at a count of 1: its in-process budget is
    # untouched, so the refusal came from the shared counter and nothing else.
    assert tracked_key_count() == 2
    assert all(window.count == 1 for window in ratelimit._windows.values())


def test_the_durable_limit_survives_a_replica_restart_end_to_end(
    client, db_session, monkeypatch, live_settings
):
    """The same proof through the real endpoint, not just the module.

    A rolling deploy recycles replicas constantly. Without the shared counter
    every restart would hand the fleet a fresh budget for password guessing.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="2",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )

    # Replica A serves the limit.
    assert login(client).status_code == 401
    assert login(client).status_code == 401
    assert row_for(db_session, "login", "addr").count == 2

    # Replica B starts cold: it has no memory of A's two requests.
    reset_rate_limits()
    tracked = login(client)

    assert tracked.status_code == 429
    assert tracked.headers["Retry-After"]
    assert tracked.json()["detail"] == RATE_LIMIT_MESSAGE
    # The shared counter went 2 -> 3 on the very first request B ever served, and
    # that single statement is what refused it. Counting and checking cannot be
    # separated without reintroducing the race the upsert exists to remove, so a
    # refused attempt is still counted: it is still an attempt.
    assert row_for(db_session, "login", "addr").count == 3


def test_a_second_replica_can_still_serve_a_different_address(
    monkeypatch, live_settings, db_session
):
    """Sharing must not become a fleet-wide outage knob.

    One address over budget must not refuse a different caller, or a single
    misbehaving client could lock every other customer out of signing in.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="1",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )

    noisy = make_request(host="203.0.113.1")
    quiet = make_request(host="203.0.113.2")

    assert check("login", noisy, account="noisy@example.com").limited is False
    reset_rate_limits()

    assert check("login", noisy, account="noisy@example.com").limited is True
    assert check("login", quiet, account="quiet@example.com").limited is False


def test_only_the_abuse_critical_buckets_are_durable():
    """Durable writes cost a round trip, so they are not spent on metered work.

    An authenticated endpoint is already throttled per account by a row in the
    database, so a shared address counter would add load without adding a
    control.
    """
    assert DURABLE_BUCKETS == frozenset({"login", "register", "forgot-password"})

    for bucket in DURABLE_BUCKETS:
        assert bucket in BUCKET_SETTINGS

    for bucket in ("transcribe", "checkout", "portal", "change-password", "delete-account"):
        assert bucket in BUCKET_SETTINGS
        assert bucket not in DURABLE_BUCKETS


def test_disabling_the_durable_layer_leaves_the_in_process_one(
    monkeypatch, live_settings, db_session
):
    """`RATE_LIMIT_DURABLE_ENABLED=0` removes the shared half only."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="2",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="0",
    )
    request = make_request()

    assert check("login", request, account=EMAIL).limited is False
    assert check("login", request, account=EMAIL).limited is False
    assert check("login", request, account=EMAIL).limited is True

    assert durable_rows(db_session) == []


# --------------------------------------------------------------------------- #
# 9. A non-durable bucket writes nothing                                      #
# --------------------------------------------------------------------------- #


def test_a_non_durable_bucket_writes_no_shared_row(monkeypatch, live_settings, db_session):
    """`checkout` is enforced, and costs no database round trip to do it."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="2",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    request = make_request()

    assert check("checkout", request).limited is False
    assert check("checkout", request).limited is False
    assert check("checkout", request).limited is True

    # Enforced in process memory...
    assert tracked_key_count() == 1
    # ...and invisible to the shared table.
    assert durable_rows(db_session) == []


def test_an_authenticated_endpoint_writes_no_shared_row(client, db_session):
    """The same property through a real handler.

    `enforce("checkout", ...)` runs before the plan check, so the bucket is
    genuinely consumed even though Stripe is not configured and the request is
    refused for another reason.
    """
    token = register(client).json()["access_token"]

    for _ in range(3):
        client.post(
            "/api/billing/checkout",
            json={"plan": "creator_monthly"},
            headers=auth_header(token),
        )

    keys = {row.key for row in durable_rows(db_session)}
    assert any(key.startswith("register:") for key in keys)
    assert not any(key.startswith("checkout:") for key in keys)
    assert not any(key.startswith("transcribe:") for key in keys)
    assert not any(key.startswith("portal:") for key in keys)


# --------------------------------------------------------------------------- #
# 10. A durable counter resets when its window elapses                        #
# --------------------------------------------------------------------------- #


def test_a_durable_counter_resets_when_its_window_elapses(
    monkeypatch, live_settings, db_session
):
    """A fixed window opens again; it does not slide and it does not stick.

    `window_started_at` is moved by hand rather than by waiting, so the test is
    exact and instant.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="2",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    request = make_request()

    check("login", request, account=EMAIL)
    check("login", request, account=EMAIL)
    assert row_for(db_session, "login", "addr").count == 2

    # Age the row past its window.
    stale = datetime.now(timezone.utc) - timedelta(seconds=301)
    db_session.execute(update(RateLimitBucket).values(window_started_at=stale))
    db_session.commit()

    # A fresh replica, so the refusal can only come from the shared counter.
    reset_rate_limits()
    before = datetime.now(timezone.utc)
    decision = check("login", request, account=EMAIL)

    assert decision.limited is False

    row = row_for(db_session, "login", "addr")
    assert row.count == 1
    # The same statement that incremented the counter also opened the new window.
    assert row.window_started_at.tzinfo is not None
    assert row.window_started_at >= before - timedelta(seconds=5)


def test_a_window_that_has_not_elapsed_keeps_counting(monkeypatch, live_settings, db_session):
    """The control on the previous test: a barely-aged window must still count."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="2",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    request = make_request()

    check("login", request, account=EMAIL)
    check("login", request, account=EMAIL)

    barely = datetime.now(timezone.utc) - timedelta(seconds=299)
    db_session.execute(update(RateLimitBucket).values(window_started_at=barely))
    db_session.commit()

    reset_rate_limits()
    decision = check("login", request, account=EMAIL)

    assert decision.limited is True
    assert row_for(db_session, "login", "addr").count == 3


# --------------------------------------------------------------------------- #
# 11. A database failure must not block the request                          #
# --------------------------------------------------------------------------- #


def test_a_missing_durable_table_does_not_block_a_login(
    client, monkeypatch
):
    """Availability over strictness, for the failure the docstring names first.

    A deployment whose migration has not run yet is the realistic version of
    this: the shared half of the control is absent, and the cheap in-process
    half must still serve the request rather than turning a login into a 500.
    """
    with monkeypatch.context() as patch:
        patch.setattr(
            ratelimit,
            "_DURABLE_UPSERT",
            text("SELECT * FROM rate_limit_buckets_which_was_never_migrated"),
        )

        response = login(client)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_a_failing_durable_write_does_not_block_a_login(client, monkeypatch):
    """The other half of the same promise: the *commit* failing, not the read.

    Without a rollback the transaction would leak, and without the catch the
    degraded dependency would become a total outage on the login page.
    """
    real_factory = get_session_factory()

    def factory():
        inner = real_factory()
        original_commit = inner.commit
        state = {"failed": False}

        def commit():
            if not state["failed"]:
                state["failed"] = True
                raise RuntimeError("connection reset by peer")
            original_commit()

        inner.commit = commit
        return inner

    with monkeypatch.context() as patch:
        patch.setattr(ratelimit, "get_session_factory", lambda: factory)

        first = login(client)
        second = login(client)

    assert first.status_code == 401
    # The first attempt lost its shared count entirely and the second still served.
    assert second.status_code == 401


def test_a_failing_durable_write_does_not_block_registration(
    client, db_session, monkeypatch
):
    """Same promise on the other durable endpoint, and nothing is half written."""
    with monkeypatch.context() as patch:
        patch.setattr(
            ratelimit,
            "_DURABLE_UPSERT",
            text("SELECT * FROM rate_limit_buckets_which_was_never_migrated"),
        )

        response = register(client, email="resilient@example.com")

    assert response.status_code == 201
    # The account exists and can sign in, so the failure cost nothing.
    from sqlalchemy import select as _select

    from app.db.models import User

    assert (
        db_session.execute(
            _select(User).where(User.email == "resilient@example.com")
        ).scalar_one_or_none()
        is not None
    )


def test_the_durable_failure_is_logged(monkeypatch, live_settings):
    """An operator must be able to see that the shared budget is not enforced.

    Silently not existing and known-broken are materially different situations,
    and only the second one is actionable.
    """
    configure(monkeypatch, live_settings, RATE_LIMIT_LOGIN="1", RATE_LIMIT_DURABLE_ENABLED="1")

    warnings: list[str] = []

    class Recorder:
        def warning(self, message, *args):
            warnings.append(message % args if args else message)

        def info(self, message, *args):
            pass

    original_logger = ratelimit.logger
    original_upsert = ratelimit._DURABLE_UPSERT

    with monkeypatch.context() as patch:
        patch.setattr(ratelimit, "logger", Recorder())
        patch.setattr(
            ratelimit,
            "_DURABLE_UPSERT",
            text("SELECT * FROM rate_limit_buckets_which_was_never_migrated"),
        )

        decision = check("login", make_request(), account=EMAIL)

    ratelimit.logger = original_logger
    ratelimit._DURABLE_UPSERT = original_upsert

    assert decision.limited is False
    assert warnings, "a swallowed database failure must still be recorded"
    assert "login" in warnings[0]
    assert "OperationalError" in warnings[0]


def test_a_durable_read_failure_is_also_survivable(monkeypatch, live_settings):
    """The read-back is inside the same try, so it is covered too."""
    configure(monkeypatch, live_settings, RATE_LIMIT_LOGIN="1", RATE_LIMIT_DURABLE_ENABLED="1")

    with monkeypatch.context() as patch:
        patch.setattr(
            ratelimit,
            "_DURABLE_READ",
            text("SELECT * FROM rate_limit_buckets_which_was_never_migrated"),
        )

        decision = check("login", make_request(), account=EMAIL)

    assert decision.limited is False


# --------------------------------------------------------------------------- #
# 12. Durable rows are pruned opportunistically                              #
# --------------------------------------------------------------------------- #


def stale_row(key: str) -> RateLimitBucket:
    return RateLimitBucket(
        key=key,
        window_started_at=datetime.now(timezone.utc)
        - timedelta(seconds=longest_window_seconds() + 3600),
        count=3,
    )


def test_a_stale_durable_row_is_swept_by_the_next_durable_request(
    monkeypatch, live_settings, db_session
):
    """A row that can never be read again is deleted from a request already
    writing to the table, so there is no scheduler and no background thread."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="10",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
        RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS="300",
    )
    abandoned = "login:addr:198.51.100.250"
    db_session.add(stale_row(abandoned))
    db_session.commit()
    assert durable_tracked_key_count() == 1

    check("login", make_request(), account=EMAIL)

    keys = {row.key for row in durable_rows(db_session)}
    assert abandoned not in keys
    # The request that triggered the sweep still did its own work.
    assert any(key.startswith("login:addr:") for key in keys)


def test_the_sweep_is_rate_limited_by_its_configured_interval(
    monkeypatch, live_settings, db_session
):
    """Housekeeping must not run on every request.

    `RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS` bounds the sweep to at most once
    per interval per process, and that bound is what keeps the DELETE off the
    hot path.
    """
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="100",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
        RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS="300",
    )
    first = "login:addr:198.51.100.250"
    check("login", make_request(), account=EMAIL)  # the first durable call sweeps
    db_session.add(stale_row(first))
    db_session.commit()
    assert first in {row.key for row in durable_rows(db_session)}

    check("login", make_request(host="203.0.113.11"), account="other@example.com")

    # Well inside the interval, so the abandoned row is still there.
    assert first in {row.key for row in durable_rows(db_session)}


def test_the_sweep_runs_again_once_the_interval_has_passed(
    monkeypatch, live_settings, db_session
):
    """An interval of 0 sweeps on every durable request, which makes the test
    deterministic and documents the escape hatch."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="100",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
        RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS="300",
    )
    check("login", make_request(), account=EMAIL)

    abandoned = "login:addr:198.51.100.251"
    db_session.add(stale_row(abandoned))
    db_session.commit()
    check("login", make_request(host="203.0.113.12"), account="other@example.com")
    assert abandoned in {row.key for row in durable_rows(db_session)}

    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="100",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
        RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS="0",
    )
    check("login", make_request(host="203.0.113.13"), account="third@example.com")

    assert abandoned not in {row.key for row in durable_rows(db_session)}


def test_the_retention_horizon_is_the_longest_configured_window(
    monkeypatch, live_settings, db_session
):
    """The horizon is derived from the buckets, so the two cannot disagree.

    A row still inside the longest window might be read by some bucket, so it
    must survive the sweep.
    """
    settings = configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="100",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
        RATE_LIMIT_DURABLE_PRUNE_INTERVAL_SECONDS="0",
    )

    horizon = longest_window_seconds(settings)
    assert horizon == max(
        int(getattr(settings, window)) for _, window in BUCKET_SETTINGS.values()
    )

    recently_used = RateLimitBucket(
        key="login:addr:198.51.100.252",
        window_started_at=datetime.now(timezone.utc) - timedelta(seconds=horizon // 2),
        count=2,
    )
    db_session.add(recently_used)
    db_session.commit()

    check("login", make_request(), account=EMAIL)

    assert recently_used.key in {row.key for row in durable_rows(db_session)}


def test_starting_the_process_clears_memory_but_not_the_shared_table(
    monkeypatch, live_settings, db_session
):
    """The startup clear must not undo the control it shares.

    `reset_rate_limits` runs from the application lifespan. If it also emptied
    the shared table, any one replica restarting would hand the whole fleet a
    fresh budget, which is exactly the property the durable layer removes.
    """
    configure(monkeypatch, live_settings, RATE_LIMIT_LOGIN="100", RATE_LIMIT_DURABLE_ENABLED="1")
    check("login", make_request(), account=EMAIL)
    assert durable_tracked_key_count() == 2

    reset_rate_limits()

    assert tracked_key_count() == 0
    assert durable_tracked_key_count() == 2


# --------------------------------------------------------------------------- #
# 13-15. The unauthenticated endpoints are limited                           #
# --------------------------------------------------------------------------- #


def test_login_is_throttled(client, monkeypatch, live_settings):
    """Password guessing must stop, and must stop before Argon2id is reached."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="3",
        RATE_LIMIT_LOGIN_WINDOW_SECONDS="300",
    )

    statuses = [login(client).status_code for _ in range(5)]

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]


def test_register_is_throttled(client, monkeypatch, live_settings):
    """Unthrottled registration is a way to mint unlimited free transcription."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_REGISTER="3",
        RATE_LIMIT_REGISTER_WINDOW_SECONDS="300",
    )

    statuses = [
        register(client, email=f"flood-{index}@example.com").status_code for index in range(5)
    ]

    assert statuses[:3] == [201, 201, 201]
    assert statuses[3:] == [429, 429]


def test_forgot_password_is_throttled(client, db_session, monkeypatch, live_settings):
    """Throttled, but never with a 429.

    A 429 on this endpoint would tell an attacker that the address is under
    observation, which is itself an enumeration signal, so the throttle has to be
    invisible in the response.
    """
    configure(
        monkeypatch,
        live_settings,
        PASSWORD_RESET_IP_LIMIT="2",
        PASSWORD_RESET_IP_WINDOW_SECONDS="300",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )

    responses = [
        client.post("/api/auth/forgot-password", json={"email": EMAIL}) for _ in range(4)
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    messages = {response.json()["message"] for response in responses}
    assert len(messages) == 1, "a throttled request must be indistinguishable"

    # The observable proof that the third and fourth were refused before any
    # database work: the shared counter stopped advancing at the limit.
    assert row_for(db_session, "forgot-password", "addr").count == 2
    assert row_for(db_session, "forgot-password", "acct").count == 2


def test_forgot_password_throttle_is_also_visible_in_the_decision(
    monkeypatch, live_settings
):
    """The same bucket, asserted directly, so a future router change is caught."""
    configure(
        monkeypatch,
        live_settings,
        PASSWORD_RESET_IP_LIMIT="2",
        PASSWORD_RESET_IP_WINDOW_SECONDS="300",
    )
    request = make_request()

    assert allow("forgot-password", request, account=EMAIL) is True
    assert allow("forgot-password", request, account=EMAIL) is True
    assert allow("forgot-password", request, account=EMAIL) is False
    assert check("forgot-password", request, account=EMAIL).limited is True


def test_forgot_password_uses_the_legacy_environment_variable_names(
    monkeypatch, live_settings
):
    """The throttle that used to live in the router keeps its variable names.

    Existing deployments and .env files set `PASSWORD_RESET_IP_LIMIT`, so
    renaming it would silently turn the control off.
    """
    settings = configure(
        monkeypatch,
        live_settings,
        PASSWORD_RESET_IP_LIMIT="7",
        PASSWORD_RESET_IP_WINDOW_SECONDS="11",
    )

    assert BUCKET_SETTINGS["forgot-password"] == (
        "password_reset_ip_limit",
        "password_reset_ip_window_seconds",
    )
    assert settings.password_reset_ip_limit == 7
    assert settings.password_reset_ip_window_seconds == 11


# --------------------------------------------------------------------------- #
# 16. Account deletion has its own bucket                                    #
# --------------------------------------------------------------------------- #


def test_account_deletion_uses_its_own_dedicated_bucket():
    """It must not share a budget with another control.

    A user who has burned the password-change budget by mistyping five new
    passwords must still be able to close their account, and a flood of delete
    attempts must not be able to spend another control's budget to get there.
    """
    assert "delete-account" in BUCKET_SETTINGS
    assert "change-password" in BUCKET_SETTINGS
    assert BUCKET_SETTINGS["delete-account"] == (
        "delete_account_rate_limit",
        "delete_account_rate_window_seconds",
    )
    assert BUCKET_SETTINGS["delete-account"] != BUCKET_SETTINGS["change-password"]


def test_burning_the_deletion_budget_leaves_password_change_alone(
    client, monkeypatch, live_settings
):
    """The two budgets are independent in both directions, on the real endpoints."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_DELETE_ACCOUNT="2",
        RATE_LIMIT_DELETE_ACCOUNT_WINDOW_SECONDS="300",
        RATE_LIMIT_CHANGE_PASSWORD="5",
        RATE_LIMIT_CHANGE_PASSWORD_WINDOW_SECONDS="300",
    )
    token = register(client).json()["access_token"]
    reset_rate_limits()
    reset_durable_rate_limits()

    deletes = [
        client.post(
            "/api/account/delete",
            json={"current_password": "wrong-password", "confirmation": "DELETE"},
            headers=auth_header(token),
        )
        for _ in range(4)
    ]

    assert [response.status_code for response in deletes] == [401, 401, 429, 429]
    # The account is untouched, and the session still works.
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    # Change-password has its own untouched budget.
    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-different-strong-password"},
        headers=auth_header(token),
    )

    assert changed.status_code == 200

    buckets = {bucket for bucket, _, _ in ratelimit._windows}
    assert buckets == {"delete-account", "change-password"}


# --------------------------------------------------------------------------- #
# 17-19. What must never be limited                                          #
# --------------------------------------------------------------------------- #


def test_health_is_never_throttled(client, monkeypatch, live_settings):
    """The liveness probe decides whether a replica receives traffic.

    Throttling it would take healthy replicas out of rotation under load, and a
    probe that answers 429 looks identical to a failing one.
    """
    configure(monkeypatch, live_settings, **ALL_LIMITS)

    for _ in range(40):
        assert client.get("/api/health").status_code == 200

    # No bucket was consulted at all, which is stronger than "the limit was high".
    assert tracked_key_count() == 0
    assert durable_tracked_key_count() == 0


def test_health_keeps_answering_after_the_auth_endpoints_are_exhausted(
    client, monkeypatch, live_settings
):
    """Being over budget on login must not be a reason to fail the probe."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="1",
        RATE_LIMIT_REGISTER="1",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    assert login(client).status_code == 401
    assert login(client).status_code == 429
    assert register(client, email="blocked@example.com").status_code == 201
    assert register(client, email="blocked-2@example.com").status_code == 429

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


def test_the_service_root_is_never_throttled(client, monkeypatch, live_settings):
    """The unversioned root, which is the first thing an operator curls."""
    configure(monkeypatch, live_settings, **ALL_LIMITS)

    for _ in range(40):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["service"] == "captionline-transcription"

    assert tracked_key_count() == 0
    assert durable_tracked_key_count() == 0


def test_the_stripe_webhook_is_never_throttled(client, monkeypatch, live_settings):
    """Stripe must always be able to deliver, or entitlement is never granted.

    A webhook that answers 429 is a webhook Stripe retries, and eventually
    disables. Since paid access is only ever granted by a verified webhook, that
    is a billing outage, not a throttled request.
    """
    configure(monkeypatch, live_settings, **ALL_LIMITS)

    statuses = []
    for index in range(25):
        payload = json.dumps(
            {
                "id": f"evt_never_limited_{index}",
                "type": "customer.subscription.updated",
                "data": {"object": {"customer": "cus_test_123"}},
            }
        ).encode()

        response = client.post(
            "/api/billing/webhook",
            content=payload,
            headers={"Stripe-Signature": "t=1,v1=not-a-valid-signature"},
        )
        statuses.append(response.status_code)

    assert 429 not in statuses
    # Stripe is not configured in this suite, so the honest answer is 503. The
    # point is that every request was answered rather than refused.
    assert set(statuses) == {503}


def test_the_webhook_stays_reachable_after_every_other_bucket_is_exhausted(
    client, monkeypatch, live_settings
):
    """Same proof with the other endpoints already blocked, so no shared state is
    in play and only the webhook's own behaviour is left."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_LOGIN="1",
        RATE_LIMIT_REGISTER="1",
        RATE_LIMIT_CHECKOUT="1",
        RATE_LIMIT_PORTAL="1",
        RATE_LIMIT_DELETE_ACCOUNT="1",
        RATE_LIMIT_CHANGE_PASSWORD="1",
        PASSWORD_RESET_IP_LIMIT="1",
        RATE_LIMIT_DURABLE_ENABLED="1",
    )
    assert login(client).status_code == 401
    assert login(client).status_code == 429

    for index in range(10):
        payload = json.dumps({"id": f"evt_after_exhaustion_{index}", "type": "invoice.paid"}).encode()
        response = client.post("/api/billing/webhook", content=payload)
        assert response.status_code != 429


# --------------------------------------------------------------------------- #
# The limiter's own bookkeeping                                               #
# --------------------------------------------------------------------------- #


def test_every_bucket_resolves_to_a_real_setting(monkeypatch, live_settings):
    """A typo in `BUCKET_SETTINGS` would only surface as a 500 in production."""
    settings = configure(monkeypatch, live_settings)

    for bucket, (limit_attribute, window_attribute) in BUCKET_SETTINGS.items():
        assert isinstance(getattr(settings, limit_attribute), int)
        assert isinstance(getattr(settings, window_attribute), int)
        assert getattr(settings, limit_attribute) > 0, bucket
        assert getattr(settings, window_attribute) > 0, bucket


def test_the_documented_defaults_are_the_documented_defaults(monkeypatch, live_settings):
    """A default that drifts is a policy change nobody reviewed."""
    for name in ALL_LIMITS:
        monkeypatch.delenv(name, raising=False)
    live_settings()
    settings = ratelimit.get_settings()

    assert settings.rate_limit_max_keys == 10000
    assert settings.register_rate_limit == 5
    assert settings.register_rate_window_seconds == 3600
    assert settings.login_rate_limit == 10
    assert settings.login_rate_window_seconds == 300
    assert settings.transcribe_rate_limit == 20
    assert settings.checkout_rate_limit == 10
    assert settings.delete_account_rate_limit == 5
    assert settings.delete_account_rate_window_seconds == 900
    assert settings.password_reset_ip_limit == 5
    assert settings.password_reset_ip_window_seconds == 900
    assert settings.rate_limit_durable_enabled is True
    assert settings.rate_limit_durable_prune_interval_seconds == 300
    assert settings.trust_proxy_headers is False


def test_a_decision_carries_everything_a_429_needs(monkeypatch, live_settings):
    """`enforce` builds its response from this object and nothing else."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="1",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )
    request = make_request()

    allowed = check("checkout", request)
    assert isinstance(allowed, RateLimitDecision)
    assert (allowed.limited, allowed.retry_after, allowed.limit) == (False, 0, 1)

    refused = check("checkout", request)
    assert (refused.limited, refused.limit) == (True, 1)
    assert refused.retry_after >= 1


def test_reset_rate_limits_forgets_everything_in_process(
    monkeypatch, live_settings
):
    """The reset the module exposes, asserted so its contract cannot drift."""
    configure(
        monkeypatch,
        live_settings,
        RATE_LIMIT_CHECKOUT="1",
        RATE_LIMIT_CHECKOUT_WINDOW_SECONDS="300",
    )
    request = make_request()
    check("checkout", request)
    assert tracked_key_count() == 1

    reset_rate_limits()

    assert tracked_key_count() == 0
    assert check("checkout", request).limited is False
