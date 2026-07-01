# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.approvals + FK from dispatches.approval_id

Revision ID: 0003_sol_approvals
Revises: 0002_sol_dispatches
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_sol_approvals"
down_revision = "0002_sol_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dispatch_id",
            sa.BigInteger(),
            sa.ForeignKey("sol.dispatches.id"),
            nullable=True,
        ),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("args_json", postgresql.JSONB(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("delivery_channels", postgresql.JSONB(), nullable=False),
        sa.Column(
            "delivery_log",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("callback_token", sa.Text(), nullable=True),
        schema="sol",
    )
    op.create_index(
        "ix_approvals_status_expires",
        "approvals",
        ["status", "expires_at"],
        schema="sol",
    )
    op.create_index(
        "ix_approvals_tenant_status",
        "approvals",
        ["tenant_id", "status"],
        schema="sol",
    )
    op.create_index("ix_approvals_trace", "approvals", ["trace_id"], schema="sol")

    op.create_foreign_key(
        "fk_dispatches_approval",
        source_table="dispatches",
        referent_table="approvals",
        local_cols=["approval_id"],
        remote_cols=["id"],
        source_schema="sol",
        referent_schema="sol",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dispatches_approval",
        "dispatches",
        type_="foreignkey",
        schema="sol",
    )
    op.drop_index("ix_approvals_trace", table_name="approvals", schema="sol")
    op.drop_index("ix_approvals_tenant_status", table_name="approvals", schema="sol")
    op.drop_index("ix_approvals_status_expires", table_name="approvals", schema="sol")
    op.drop_table("approvals", schema="sol")
