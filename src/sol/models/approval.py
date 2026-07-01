# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.approvals — approval queue (absorbs Brain's pending_actions in Phase 3.2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = {"schema": "sol"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dispatch_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    capability: Mapped[str] = mapped_column(String, nullable=False)
    args_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_channels: Mapped[list] = mapped_column(JSONB, nullable=False)
    delivery_log: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String, nullable=True)
    callback_token: Mapped[str | None] = mapped_column(String, nullable=True)
