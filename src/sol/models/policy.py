"""sol.policies — cross-capability rules."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("version", "rule_id", name="uq_policies_version_rule"),
        {"schema": "sol"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_kind: Mapped[str] = mapped_column(String, nullable=False)
    match_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_field: Mapped[str | None] = mapped_column(String, nullable=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
