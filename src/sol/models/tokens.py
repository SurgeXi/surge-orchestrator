# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.issued_tokens + sol.revoked_tokens — token audit + revocation."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from ..db import Base


class IssuedToken(Base):
    __tablename__ = "issued_tokens"
    __table_args__ = {"schema": "sol"}

    jti: Mapped[str] = mapped_column(String, primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    issued_by: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # admin | service
    audience: Mapped[str] = mapped_column(String, nullable=False)
    capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kid: Mapped[str | None] = mapped_column(String, nullable=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    __table_args__ = {"schema": "sol"}

    jti: Mapped[str] = mapped_column(
        String, ForeignKey("sol.issued_tokens.jti"), primary_key=True
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_by: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
