# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""GET /v1/sol/audit — audit ledger query."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Dispatch
from .deps import get_caller

router = APIRouter()


@router.get("/audit")
def query_audit(
    tenant_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_caller),
) -> dict:
    q = db.query(Dispatch)
    if tenant_id:
        q = q.filter(Dispatch.tenant_id == tenant_id)
    if actor_id:
        q = q.filter(Dispatch.actor_id == actor_id)
    if capability:
        q = q.filter(Dispatch.capability == capability)
    if since:
        q = q.filter(Dispatch.created_at >= since)
    if until:
        q = q.filter(Dispatch.created_at <= until)
    if trace_id:
        q = q.filter(Dispatch.trace_id == trace_id)
    rows = q.order_by(Dispatch.created_at.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "audit_id": str(r.audit_id),
                "trace_id": r.trace_id,
                "tenant_id": r.tenant_id,
                "actor_id": r.actor_id,
                "actor_tier": r.actor_tier,
                "capability": r.capability,
                "decision": r.decision,
                "decision_path": r.decision_path,
                "decision_reason": r.decision_reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }
