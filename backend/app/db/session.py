"""Engine and session management.

The database is optional so local development and transcription-only setups keep
working without one. When `DATABASE_URL` is absent, `is_configured()` returns
False and the auth/account endpoints report that clearly instead of failing at
import time.
"""

from __future__ import annotations

import logging
from typing import Iterator

from fastapi import HTTPException, status
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from ..config import get_settings

logger = logging.getLogger(__name__)

DATABASE_UNAVAILABLE = (
    "Accounts are unavailable because no database is configured on this service."
)

_engine: Engine | None = None
_session_factory: sessionmaker[OrmSession] | None = None


def normalize_database_url(url: str) -> str:
    """Normalize a platform-provided URL into a SQLAlchemy psycopg URL.

    Railway and several Postgres hosts hand out `postgres://` or
    `postgresql://`. SQLAlchemy needs an explicit driver and a
    `postgresql://` scheme, so both are rewritten.
    """
    value = url.strip()

    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    elif value.startswith("postgresql://"):
        value = "postgresql://" + value[len("postgresql://") :]

    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]

    return value


def is_configured() -> bool:
    """Whether a database URL was provided."""
    return bool(get_settings().database_url)


def get_engine() -> Engine | None:
    """Return the lazily created engine, or None when no database is configured."""
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    settings = get_settings()
    raw_url = settings.database_url

    if not raw_url:
        return None

    url = normalize_database_url(raw_url)
    kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}

    if settings.database_echo:
        kwargs["echo"] = True

    if url.startswith("sqlite"):
        # Local verification only; FastAPI serves requests from a threadpool.
        kwargs["connect_args"] = {"check_same_thread": False}

    # Never log the URL: it embeds credentials.
    logger.info("Creating database engine (driver=%s)", url.split("://", 1)[0])

    _engine = create_engine(url, **kwargs)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    return _engine


def get_session_factory() -> sessionmaker[OrmSession] | None:
    get_engine()
    return _session_factory


def reset_engine() -> None:
    """Drop the cached engine. Used by tests and after a configuration change."""
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _session_factory = None


def get_db() -> Iterator[OrmSession]:
    """FastAPI dependency yielding a database session.

    This is a dependency, so it is resolved *before* the route body runs. It
    therefore raises the 503 itself; relying on a check inside the handler would
    be too late and would surface as an unhandled error.
    """
    factory = get_session_factory()

    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DATABASE_UNAVAILABLE,
        )

    session = factory()
    try:
        yield session
    finally:
        session.close()
