# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.learned_tiers

Revision ID: 0005_sol_learned_tiers
Revises: 0004_sol_policies
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_sol_learned_tiers"
down_revision = "0004_sol_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learned_tiers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "capability",
            sa.Text(),
            sa.ForeignKey("sol.capabilities.name"),
            nullable=False,
        ),
        sa.Column("pattern_hash", sa.Text(), nullable=False),
        sa.Column("pattern_description", sa.Text(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("approval_count", sa.Integer(), nullable=False),
        sa.Column("denial_count", sa.Integer(), nullable=False),
        sa.Column("last_denial_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("proposed_min_tier", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("todd_decision", sa.Text(), nullable=True),
        sa.Column("todd_decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("capability", "pattern_hash", name="uq_learned_tiers_pattern"),
        schema="sol",
    )
    op.create_index(
        "ix_learned_tiers_active",
        "learned_tiers",
        ["capability"],
        schema="sol",
        postgresql_where=sa.text("active=true"),
    )
    op.create_index(
        "ix_learned_tiers_pending_todd",
        "learned_tiers",
        ["updated_at"],
        schema="sol",
        postgresql_where=sa.text("todd_decision='pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_learned_tiers_pending_todd", table_name="learned_tiers", schema="sol")
    op.drop_index("ix_learned_tiers_active", table_name="learned_tiers", schema="sol")
    op.drop_table("learned_tiers", schema="sol")
