# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Pydantic schemas for approval decisions."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ApprovalDecide(BaseModel):
    decision: Literal["approved", "denied"]
    reason: str | None = None


class ApprovalRead(BaseModel):
    id: uuid.UUID
    dispatch_id: int | None
    trace_id: str
    tenant_id: str
    actor_kind: str
    actor_id: str
    capability: str
    args_json: dict[str, Any]
    intent: str | None
    delivery_channels: list[str]
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
