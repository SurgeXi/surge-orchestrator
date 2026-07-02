# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.capabilities

Revision ID: 0001_sol_capabilities
Revises:
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_sol_capabilities"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sol")
    op.create_table(
        "capabilities",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("owner_service", sa.Text(), nullable=False),
        sa.Column("min_tier", sa.Integer(), nullable=False),
        sa.Column("handler_kind", sa.Text(), nullable=False),
        sa.Column("handler_endpoint", sa.Text(), nullable=False),
        sa.Column("args_schema_json", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rate_limit_json", postgresql.JSONB(), nullable=True),
        sa.Column("requires_human", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expiry_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "registered_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_registered_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        schema="sol",
    )
    op.create_index(
        "ix_capabilities_owner",
        "capabilities",
        ["owner_service"],
        schema="sol",
    )
    op.create_index(
        "ix_capabilities_status",
        "capabilities",
        ["status"],
        schema="sol",
        postgresql_where=sa.text("status='active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_capabilities_status", table_name="capabilities", schema="sol")
    op.drop_index("ix_capabilities_owner", table_name="capabilities", schema="sol")
    op.drop_table("capabilities", schema="sol")
