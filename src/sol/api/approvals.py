"""Approval queue + decide endpoint (stubs; full impl lands Week 2)."""
from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Approval
from ..schemas.approval import ApprovalDecide, ApprovalRead
from .deps import require_approver

router = APIRouter()


@router.get("/approvals/pending", response_model=list[ApprovalRead])
def list_pending(
    tenant_id: str | None = None,
    actor_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _=Depends(require_approver),
) -> list[ApprovalRead]:
    q = db.query(Approval).filter(Approval.status == "pending")
    if tenant_id:
        q = q.filter(Approval.tenant_id == tenant_id)
    if actor_id:
        q = q.filter(Approval.actor_id == actor_id)
    rows = q.order_by(Approval.created_at.asc()).limit(min(limit, 200)).all()
    return [_to_read(r) for r in rows]


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalRead)
def decide(
    approval_id: uuid.UUID,
    payload: ApprovalDecide,
    db: Session = Depends(get_db),
    caller=Depends(require_approver),
) -> ApprovalRead:
    row = db.get(Approval, approval_id)
    if row is None:
        raise HTTPException(404, detail="approval not found")
    if row.status != "pending":
        raise HTTPException(409, detail=f"approval already {row.status}")
    row.status = payload.decision
    row.decision_reason = payload.reason
    row.decided_by = caller.principal_id
    from datetime import datetime
    row.decided_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def _to_read(r: Approval) -> ApprovalRead:
    return ApprovalRead(
        id=r.id,
        dispatch_id=r.dispatch_id,
        trace_id=r.trace_id,
        tenant_id=r.tenant_id,
        actor_kind=r.actor_kind,
        actor_id=r.actor_id,
        capability=r.capability,
        args_json=r.args_json,
        intent=r.intent,
        delivery_channels=r.delivery_channels,
        status=r.status,
        created_at=r.created_at,
        expires_at=r.expires_at,
        decided_at=r.decided_at,
        decided_by=r.decided_by,
        decision_reason=r.decision_reason,
    )
