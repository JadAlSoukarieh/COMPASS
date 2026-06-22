from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db import get_app_session
from backend.app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def write_audit(
    *,
    action_type: str,
    role: str,
    result_status: str,
    detail: dict[str, Any] | None = None,
    user_id: int | None = None,
    session: Session | None = None,
) -> None:
    payload = detail or {}

    if session is not None:
        session.add(
            AuditLog(
                user_id=user_id,
                role=role,
                action_type=action_type,
                detail=payload,
                result_status=result_status,
            )
        )
        session.flush()
        return

    db_gen: Generator[Session, None, None] = get_app_session()
    db = next(db_gen)
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                role=role,
                action_type=action_type,
                detail=payload,
                result_status=result_status,
            )
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - non-fatal audit path
        db.rollback()
        logger.warning("Audit write failed: %s", exc.__class__.__name__)
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

