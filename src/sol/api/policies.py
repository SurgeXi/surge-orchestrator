"""Policy upsert + list (admin only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Policy
from ..schemas.policy import PolicyUpsertRequest, PolicyUpsertResponse
from .deps import require_admin

router = APIRouter()


@router.post("/policies/upsert", response_model=PolicyUpsertResponse)
def upsert_policies(
    payload: PolicyUpsertRequest,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
) -> PolicyUpsertResponse:
    # Deactivate prior versions.
    db.execute(update(Policy).where(Policy.active.is_(True)).values(active=False))
    for rule in payload.rules:
        row = Policy(
            version=payload.version,
            rule_id=rule.rule_id,
            description=rule.description,
            rule_kind=rule.rule_kind,
            match_json=rule.match_json,
            window_seconds=rule.window_seconds,
            scope_field=rule.scope_field,
            decision=rule.decision,
            decision_reason=rule.decision_reason,
            active=True,
            created_by=payload.created_by,
        )
        db.add(row)
    db.commit()
    return PolicyUpsertResponse(version=payload.version, rules_loaded=len(payload.rules))


@router.get("/policies")
def list_policies(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
) -> dict:
    rows = db.query(Policy).filter(Policy.active.is_(True)).all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "version": r.version,
                "rule_id": r.rule_id,
                "rule_kind": r.rule_kind,
                "decision": r.decision,
                "active": r.active,
            }
            for r in rows
        ],
    }
