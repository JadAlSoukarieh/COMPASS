from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: int
    ts: datetime
    user_id: int | None
    role: str
    action_type: str
    detail: dict[str, Any]
    result_status: str
