"""Session housekeeping.

Sessions are short-lived rows, so expired and revoked ones are purged
opportunistically rather than by a scheduler. Nothing here is required for
correctness: an expired row is already rejected on lookup, this only stops the
table growing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session as OrmSession

from ..db.models import Session as SessionModel

logger = logging.getLogger(__name__)


def purge_expired_sessions(
    db: OrmSession, older_than_days: int = 7, now: datetime | None = None
) -> int:
    """Delete sessions that expired or were revoked more than `older_than_days` ago.

    `older_than_days` exists so a just-expired session stays around briefly and
    produces the clearer "session expired" error rather than looking unknown.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(older_than_days, 0))

    result = db.execute(
        delete(SessionModel).where(
            (SessionModel.expires_at < cutoff)
            | ((SessionModel.revoked_at.is_not(None)) & (SessionModel.revoked_at < cutoff))
        )
    )
    db.commit()

    return int(result.rowcount or 0)
