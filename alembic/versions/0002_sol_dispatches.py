# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.dispatches

Revision ID: 0002_sol_dispatches
Revises: 0001_sol_capabilities
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_sol_dispatches"
down_revision = "0001_sol_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("parent_trace_id", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("actor_tier", sa.Integer(), nullable=False),
        sa.Column(
            "capability",
            sa.Text(),
            sa.ForeignKey("sol.capabilities.name"),
            nullable=False,
        ),
        sa.Column("args_hash", sa.Text(), nullable=False),
        sa.Column("args_json", postgresql.JSONB(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("identity_json", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decision_path", sa.Text(), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_status", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="sol",
    )
    op.create_index(
        "ix_dispatches_tenant_time",
        "dispatches",
        ["tenant_id", sa.text("created_at DESC")],
        schema="sol",
    )
    op.create_index(
        "ix_dispatches_actor_time",
        "dispatches",
        ["actor_id", sa.text("created_at DESC")],
        schema="sol",
    )
    op.create_index(
        "ix_dispatches_capability_time",
        "dispatches",
        ["capability", sa.text("created_at DESC")],
        schema="sol",
    )
    op.create_index("ix_dispatches_trace", "dispatches", ["trace_id"], schema="sol")
    op.create_index("ix_dispatches_decision", "dispatches", ["decision"], schema="sol")
    op.execute(
        "CREATE INDEX ix_dispatches_args_gin ON sol.dispatches "
        "USING GIN (args_json jsonb_path_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sol.ix_dispatches_args_gin")
    op.drop_index("ix_dispatches_decision", table_name="dispatches", schema="sol")
    op.drop_index("ix_dispatches_trace", table_name="dispatches", schema="sol")
    op.drop_index("ix_dispatches_capability_time", table_name="dispatches", schema="sol")
    op.drop_index("ix_dispatches_actor_time", table_name="dispatches", schema="sol")
    op.drop_index("ix_dispatches_tenant_time", table_name="dispatches", schema="sol")
    op.drop_table("dispatches", schema="sol")
