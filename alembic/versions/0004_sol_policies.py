# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.policies

Revision ID: 0004_sol_policies
Revises: 0003_sol_approvals
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_sol_policies"
down_revision = "0003_sol_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_kind", sa.Text(), nullable=False),
        sa.Column("match_json", postgresql.JSONB(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=True),
        sa.Column("scope_field", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.UniqueConstraint("version", "rule_id", name="uq_policies_version_rule"),
        schema="sol",
    )
    op.create_index(
        "ix_policies_active_version",
        "policies",
        ["version"],
        schema="sol",
        postgresql_where=sa.text("active=true"),
    )


def downgrade() -> None:
    op.drop_index("ix_policies_active_version", table_name="policies", schema="sol")
    op.drop_table("policies", schema="sol")
