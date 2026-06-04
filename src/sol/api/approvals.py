"""sol.approvals lifecycle endpoints.

Three surfaces:
  - GET  /v1/sol/approvals/pending           (admin/approver JWT)
  - POST /v1/sol/approvals/{id}/decide       (admin/approver JWT)
  - GET  /v1/sol/approvals/{id}/decide       (signed callback token)

The GET decide endpoint is the email/chat one-tap path. It accepts a
``token`` query param signed by ``auth.callback_tokens`` and verifies
that ``token``'s embedded decision matches the ``decision`` query
param so a forwarded/leaked approve URL cannot be repurposed as a
deny (and vice versa).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.callback_tokens import verify as verify_callback_token
from ..db import get_db
from ..models import Approval
from ..observability.logging import get_logger
from ..schemas.approval import ApprovalDecide, ApprovalRead
from .deps import require_approver

router = APIRouter()
log = get_logger(__name__)


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
    row.decided_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    log.info(
        "sol.approval.decided",
        approval_id=str(row.id),
        decision=row.status,
        decided_by=row.decided_by,
        path="admin-jwt",
    )
    return _to_read(row)


@router.get("/approvals/{approval_id}/decide")
def decide_by_callback(
    approval_id: uuid.UUID,
    token: str = Query(..., min_length=20),
    decision: str = Query(..., pattern="^(approve|deny|approved|denied)$"),
    db: Session = Depends(get_db),
) -> dict:
    """One-tap signed-URL decide endpoint for email/chat delivery.

    Returns a small JSON payload (HTML wrapper can be added later).
    The token's embedded decision MUST match the ``decision`` query
    param — protects against an approve URL being rewritten as deny
    or vice versa.
    """
    norm_decision = "approved" if decision in ("approve", "approved") else "denied"
    short_decision = "approve" if norm_decision == "approved" else "deny"

    claims = verify_callback_token(token)
    if claims.approval_id != approval_id:
        raise HTTPException(401, detail="callback_token_approval_mismatch")
    if claims.decision != short_decision:
        raise HTTPException(401, detail="callback_token_decision_mismatch")

    row = db.get(Approval, approval_id)
    if row is None:
        raise HTTPException(404, detail="approval not found")
    if row.status != "pending":
        # Idempotent re-click: return current state so a second click of
        # the same email link doesn't 500 the operator's browser.
        return {
            "approval_id": str(row.id),
            "status": row.status,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "note": "already_decided",
        }

    row.status = norm_decision
    row.decision_reason = f"email_one_tap:{short_decision}"
    row.decided_by = "callback-token"
    row.decided_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    log.info(
        "sol.approval.decided",
        approval_id=str(row.id),
        decision=row.status,
        decided_by=row.decided_by,
        path="callback-token",
    )
    return {
        "approval_id": str(row.id),
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat(),
    }


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
