"""Approval lifecycle service.

Creates approval rows from a dispatch, fans out delivery, and polls for
the decision. Designed to be called from the dispatch endpoint, so it
takes a session that the endpoint already owns.

Delivery channel resolution (Week 2):
  1. Email (primary) — recipient list comes from the policy cache or
     the capability's owner_service; if no recipient resolvable, fall
     back to ntfy/log_only.
  2. Log-only fallback — terminal channel, always succeeds.

The block_until_seconds parameter caps how long the caller's dispatch
will wait for a human decision. If it elapses we return status="pending"
and the caller treats that as "queued" — Brain can either fall back to
its legacy gate or surface the wait to its own caller.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..delivery.base import DeliveryAttempt, DeliveryChannel
from ..delivery.email import EmailDelivery
from ..delivery.log_only import LogOnlyDelivery
from ..models import Approval
from ..observability.logging import get_logger

log = get_logger(__name__)

DEFAULT_APPROVAL_TTL_SECONDS = 600  # 10 min default; caller can override.


def _resolve_targets(tenant_id: str, capability: str) -> list[tuple[DeliveryChannel, str]]:
    """Pick the (channel, target) pairs to attempt for this approval.

    Week 2 implementation: read from environment-driven defaults.
      SOL_APPROVER_EMAIL_DEFAULT  — single fallback email
      SOL_APPROVER_EMAIL_<tenant_id> — per-tenant override (uppercased)

    Policy-driven resolution lands Week 3+ when policy.yaml gains an
    approver_routing block. Until then, env + default keep us shipping.
    """
    import os

    pairs: list[tuple[DeliveryChannel, str]] = []
    email = (
        os.environ.get(f"SOL_APPROVER_EMAIL_{tenant_id.upper()}")
        or os.environ.get("SOL_APPROVER_EMAIL_DEFAULT")
        or ""
    ).strip()
    if email:
        pairs.append((EmailDelivery(), email))
    # log_only is always last — guarantees we leave a record even if
    # every other channel is misconfigured.
    pairs.append((LogOnlyDelivery(), f"{tenant_id}:{capability}"))
    return pairs


async def create_and_deliver(
    *,
    db: Session,
    dispatch_id: int,
    trace_id: str,
    tenant_id: str,
    actor_kind: str,
    actor_id: str,
    capability: str,
    args_json: dict[str, Any],
    intent: str | None,
    ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS,
) -> Approval:
    """Insert sol.approvals row, fan out delivery, return the row.

    Delivery is best-effort; failed attempts are recorded in delivery_log
    but never raise. The row is committed before the first delivery
    attempt so the decide endpoint can serve it even if delivery is
    still in flight.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    targets = _resolve_targets(tenant_id, capability)
    channel_names = [c.name for c, _ in targets]

    row = Approval(
        id=uuid.uuid4(),
        dispatch_id=dispatch_id,
        trace_id=trace_id,
        tenant_id=tenant_id,
        actor_kind=actor_kind,
        actor_id=actor_id,
        capability=capability,
        args_json=args_json,
        intent=intent,
        delivery_channels=channel_names,
        delivery_log=[],
        status="pending",
        expires_at=expires,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Fan out — sequential. Email + log_only is fast (<5s). Stop early
    # on the first true success so we don't double-notify.
    delivery_log_entries: list[dict[str, Any]] = []
    success_count = 0
    for channel, target in targets:
        try:
            attempt: DeliveryAttempt = await channel.deliver(approval_to_dict(row), target)
        except Exception as e:  # pragma: no cover — channels must not raise
            attempt = DeliveryAttempt(
                channel=channel.name,
                target=target,
                started_at=datetime.now(UTC),
                succeeded=False,
                response=f"channel_raised:{type(e).__name__}:{e}",
            )
        delivery_log_entries.append(
            {
                "channel": attempt.channel,
                "target": attempt.target,
                "started_at": attempt.started_at.isoformat(),
                "succeeded": attempt.succeeded,
                "response": (attempt.response or "")[:240],
            }
        )
        if attempt.succeeded:
            success_count += 1
            # log_only always succeeds; only break early on a "real" channel.
            if channel.name != "log_only":
                break

    row.delivery_log = delivery_log_entries
    db.commit()
    log.info(
        "sol.approval.created",
        approval_id=str(row.id),
        dispatch_id=dispatch_id,
        tenant=tenant_id,
        capability=capability,
        delivery_attempts=len(delivery_log_entries),
        delivery_successes=success_count,
    )
    return row


def approval_to_dict(row: Approval) -> dict[str, Any]:
    return {
        "id": row.id,
        "dispatch_id": row.dispatch_id,
        "trace_id": row.trace_id,
        "tenant_id": row.tenant_id,
        "actor_kind": row.actor_kind,
        "actor_id": row.actor_id,
        "capability": row.capability,
        "args_json": row.args_json,
        "intent": row.intent,
        "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def poll_for_decision(
    db: Session, approval_id: uuid.UUID, block_until_seconds: int
) -> Approval | None:
    """Poll the approvals row until status leaves "pending" or deadline.

    Sync poll (one DB query per ~0.5s). For block_until_seconds <= 0 we
    just return the current row without polling.
    Returns the (possibly still-pending) row, or None if missing.
    """
    deadline = time.monotonic() + max(0, block_until_seconds)
    while True:
        row = db.get(Approval, approval_id)
        if row is None:
            return None
        if row.status != "pending":
            return row
        if time.monotonic() >= deadline:
            return row
        time.sleep(0.5)
        db.expire_all()  # drop ORM cache so the next get() re-reads


async def poll_for_decision_async(
    db: Session, approval_id: uuid.UUID, block_until_seconds: int
) -> Approval | None:
    """Async variant — uses asyncio.sleep so the event loop stays responsive."""
    deadline = time.monotonic() + max(0, block_until_seconds)
    while True:
        row = db.get(Approval, approval_id)
        if row is None:
            return None
        if row.status != "pending":
            return row
        if time.monotonic() >= deadline:
            return row
        await asyncio.sleep(0.5)
        db.expire_all()
