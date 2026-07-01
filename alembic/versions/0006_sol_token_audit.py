# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.issued_tokens + sol.revoked_tokens + dispatches.auth_method

Phase 3.2 — mTLS + token rotation infrastructure.

Adds:
  - sol.issued_tokens   — append-only ledger of every token SOL issues
  - sol.revoked_tokens  — per-jti revocation set (FK to issued_tokens)
  - sol.dispatches.auth_method  — which auth path the caller used
                                  (mtls | jwt-service | jwt-admin)

Revision ID: 0006_sol_token_audit
Revises: 0005_sol_learned_tiers
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_sol_token_audit"
down_revision = "0005_sol_learned_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- issued_tokens: every issue() persists a row here ---
    op.create_table(
        "issued_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column(
            "issued_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("issued_by", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # "admin" | "service"
        sa.Column("audience", sa.Text(), nullable=False),  # subject (username or service_name)
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("kid", sa.Text(), nullable=True),  # signing key id at issue time
        schema="sol",
    )
    op.create_index(
        "ix_issued_tokens_audience", "issued_tokens", ["audience"], schema="sol"
    )
    op.create_index(
        "ix_issued_tokens_expires", "issued_tokens", ["expires_at"], schema="sol"
    )

    # --- revoked_tokens: revocation set ---
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Text(), primary_key=True),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_by", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["jti"], ["sol.issued_tokens.jti"], name="fk_revoked_tokens_jti"
        ),
        schema="sol",
    )

    # --- dispatches.auth_method ---
    op.add_column(
        "dispatches",
        sa.Column("auth_method", sa.Text(), nullable=True),
        schema="sol",
    )
    op.create_index(
        "ix_dispatches_auth_method",
        "dispatches",
        ["auth_method"],
        schema="sol",
    )


def downgrade() -> None:
    op.drop_index("ix_dispatches_auth_method", table_name="dispatches", schema="sol")
    op.drop_column("dispatches", "auth_method", schema="sol")
    op.drop_table("revoked_tokens", schema="sol")
    op.drop_index("ix_issued_tokens_expires", table_name="issued_tokens", schema="sol")
    op.drop_index("ix_issued_tokens_audience", table_name="issued_tokens", schema="sol")
    op.drop_table("issued_tokens", schema="sol")
