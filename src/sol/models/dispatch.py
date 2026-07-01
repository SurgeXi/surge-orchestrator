# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.dispatches — append-only audit ledger."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Dispatch(Base):
    __tablename__ = "dispatches"
    __table_args__ = {"schema": "sol"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    trace_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    capability: Mapped[str] = mapped_column(String, nullable=False)
    args_hash: Mapped[str] = mapped_column(String, nullable=False)
    args_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    identity_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decision_path: Mapped[str] = mapped_column(String, nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_status: Mapped[str | None] = mapped_column(String, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which auth path the caller used: mtls | jwt-service | jwt-admin
    auth_method: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
