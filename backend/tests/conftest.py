"""Shared test fixtures.

Tests run against a temporary SQLite database so the same models and the same
Alembic revision can be exercised without a PostgreSQL server. Production uses
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

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Run the real Alembic migration against the test database."""
    backend_dir = Path(__file__).resolve().parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(config, "head")

    yield

    command.downgrade(config, "base")


@pytest.fixture()
def client(migrated_database):
    """A TestClient with a clean users/sessions table per test."""
    engine = get_engine()
    assert engine is not None

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM sessions"))
        connection.execute(text("DELETE FROM users"))

    with TestClient(app) as test_client:
        yield test_client


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def db_session():
    """An ORM session for direct database assertions."""
    from app.db.session import get_session_factory

    factory = get_session_factory()
    assert factory is not None

    session = factory()
    try:
        yield session
    finally:
        session.close()
