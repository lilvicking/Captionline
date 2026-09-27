"""Shared test fixtures.

Tests run against a temporary SQLite database so the same models and the same
Alembic revisions can be exercised without a PostgreSQL server. Production uses
PostgreSQL via `DATABASE_URL`; column types are deliberately portable so the
migration is identical on both.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# The database URL must be set before app modules are imported, because settings
# are captured at import time.
_TMP_DB = Path(tempfile.gettempdir()) / "captionline_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ["WHISPERX_MODEL"] = "tiny"
os.environ["SESSION_TTL_DAYS"] = "30"
# No Stripe configuration by default, so the "not configured" paths are what the
# suite exercises unless a test opts in.
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
os.environ.pop("STRIPE_PRICE_CREATOR_MONTHLY", None)
os.environ.pop("STRIPE_PRICE_PRO_MONTHLY", None)
os.environ.pop("STRIPE_PRICE_CREATOR_ANNUAL", None)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402

#: Child rows first, so no table is cleared while another still references it.
#: Keep this list in step with the schema: a missing table leaks rows into the
#: next test, and because SQLite reuses ids after a delete, a stale row can attach
#: itself to a freshly created user.
_TABLES_IN_DELETE_ORDER = (
    "rate_limit_buckets",
    "stripe_events",
    "admin_audit_log",
    "usage_reservations",
    "password_reset_tokens",
    "sessions",
    "users",
)


def _clear_tables() -> None:
    engine = get_engine()
    assert engine is not None

    with engine.begin() as connection:
        for table in _TABLES_IN_DELETE_ORDER:
            connection.execute(text(f"DELETE FROM {table}"))


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Run the real Alembic migrations against the test database."""
    backend_dir = Path(__file__).resolve().parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(config, "head")

    yield

    command.downgrade(config, "base")


@pytest.fixture()
def db_session(migrated_database):
    """An ORM session on a clean database, for direct database assertions."""
    from app.db.session import get_session_factory

    _clear_tables()

    factory = get_session_factory()
    assert factory is not None

    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(migrated_database):
    """A TestClient on a clean database."""
    _clear_tables()

    with TestClient(app) as test_client:
        yield test_client


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def live_settings(monkeypatch):
    """Rebuild settings from the current environment for the duration of a test.

    `app.main` captures `settings` at import time, so patching environment
    variables alone would not reach the route handlers. This refreshes both the
    settings singleton and the reference held by the app module.
    """
    import app.config as config_module
    import app.main as main_module

    def refresh() -> None:
        monkeypatch.setattr(config_module, "_settings", None)
        monkeypatch.setattr(main_module, "settings", config_module.get_settings())

    refresh()
    return refresh
