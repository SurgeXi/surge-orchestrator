"""sol.learned_tiers — Phase 5 learning-system schema (lands now)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class LearnedTier(Base):
    __tablename__ = "learned_tiers"
    __table_args__ = (
        UniqueConstraint("capability", "pattern_hash", name="uq_learned_tiers_pattern"),
        {"schema": "sol"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability: Mapped[str] = mapped_column(String, nullable=False)
    pattern_hash: Mapped[str] = mapped_column(String, nullable=False)
    pattern_description: Mapped[str | None] = mapped_column(String, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_count: Mapped[int] = mapped_column(Integer, nullable=False)
    denial_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_denial_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    proposed_min_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    todd_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    todd_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
