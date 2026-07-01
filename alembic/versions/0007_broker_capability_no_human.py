# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""sol.capabilities row tweak: broker_capability defers risk to args.risk

Phase 3.3 Week 3 — when Brain routes capability calls through SOL via
the broker executor, the per-broker-capability risk class lives in
Brain's catalog. SOL only sees the umbrella ``broker_capability``
row, which had ``requires_human=true`` to be safe in shadow mode.
Now that SOL actively executes, we let the caller assert risk via
``args.risk`` and let safe broker capabilities (db_query, geo_*, ...)
auto-approve through SOL while Broker stays the source of truth on
SAFE/SCOPED/GATED/HIGH_STAKES classes.

GATED + HIGH_STAKES brokers MUST set ``args.risk = "mutate"`` (or
``"remote"``/``"destructive"``) so SOL's _needs_human() still routes
them through the human-approval queue.

Revision ID: 0007_broker_capability_no_human
Revises: 0006_sol_token_audit
"""
from __future__ import annotations

from alembic import op

revision = "0007_broker_capability_no_human"
down_revision = "0006_sol_token_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE sol.capabilities "
        "SET requires_human = false "
        "WHERE name IN ('broker_capability', 'broker_dispatch')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE sol.capabilities "
        "SET requires_human = true "
        "WHERE name IN ('broker_capability', 'broker_dispatch')"
    )
