"""Persistence helpers for the user-scoped recent runs dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.utils.logger import get_logger

from .models import UserRun
from .session import SessionLocal

logger = get_logger("db.user_runs")

ACTIVE_RUN_STATUSES = {"pending", "in_progress", "needs_review", "resuming"}


def upsert_user_run(
    *,
    request_id: str,
    user_id: str,
    kind: str,
    status: str,
    title: str | None = None,
    score: dict[str, Any] | None = None,
    result_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Create or update one dashboard activity row without blocking core work."""
    if not request_id or not user_id:
        return None
    db = SessionLocal()
    try:
        row = db.query(UserRun).filter(UserRun.request_id == request_id).first()
        if row is None:
            row = UserRun(
                request_id=request_id,
                user_id=user_id,
                kind=kind,
                status=status,
                created_at=datetime.utcnow(),
            )
            db.add(row)
        row.user_id = user_id
        row.kind = kind
        row.status = status
        if title is not None:
            row.title = title[:500]
        if score is not None:
            row.score = score
        if result_url is not None:
            row.result_url = result_url
        if metadata is not None:
            row.meta_data = metadata
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        return row.to_dict()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Failed to persist user run %s: %s", request_id, exc)
        return None
    finally:
        db.close()


def list_recent_user_runs_for_user(user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return recent product activity rows for one user as detached dictionaries."""
    safe_limit = max(1, min(limit, 50))
    db = SessionLocal()
    try:
        rows = (
            db.query(UserRun)
            .filter(UserRun.user_id == user_id)
            .order_by(UserRun.updated_at.desc(), UserRun.created_at.desc())
            .limit(safe_limit)
            .all()
        )
        return [row.to_dict() for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to list user runs for %s: %s", user_id, exc)
        return []
    finally:
        db.close()


def count_active_user_runs(user_id: str) -> int:
    """Count active dashboard jobs for the current user."""
    db = SessionLocal()
    try:
        return (
            db.query(UserRun)
            .filter(UserRun.user_id == user_id, UserRun.status.in_(ACTIVE_RUN_STATUSES))
            .count()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to count active user runs for %s: %s", user_id, exc)
        return 0
    finally:
        db.close()
