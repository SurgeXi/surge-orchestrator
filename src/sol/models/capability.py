# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.capabilities — registry of every dispatchable side-effect."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = {"schema": "sol"}

    name: Mapped[str] = mapped_column(String, primary_key=True)
    owner_service: Mapped[str] = mapped_column(String, nullable=False)
    min_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    handler_kind: Mapped[str] = mapped_column(String, nullable=False)
    handler_endpoint: Mapped[str] = mapped_column(String, nullable=False)
    args_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    rate_limit_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requires_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    expiry_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'")
    )
