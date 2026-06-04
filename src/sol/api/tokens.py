"""Token administration: issue + revoke + list.

Endpoints:
  POST   /v1/sol/admin/issue-token       — admin only; issues + persists to issued_tokens
  POST   /v1/sol/tokens/{jti}/revoke     — admin only; adds to revoked_tokens
  GET    /v1/sol/tokens/issued           — admin only; list (paginated)
  GET    /v1/sol/tokens/revoked          — admin only; list

Issuance and revocation both write a dispatch audit row (capability =
sol_issue_token or sol_revoke_token) so token-mgmt is auditable like any
other side-effect.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.jwt import AdminJwtAuth
from ..auth.keystore import current_signing_key
from ..auth.revocation import add_revoked
from ..auth.service_tokens import ServiceTokenAuth
from ..db import get_db
from ..models import Dispatch, IssuedToken, RevokedToken
from ..observability.logging import get_logger
from ..settings import get_settings
from .deps import CallerContext, require_admin

router = APIRouter()
log = get_logger(__name__)


class IssueTokenRequest(BaseModel):
    kind: Literal["admin", "service"]
    subject: str = Field(..., description="username (admin) or service_name (service)")
    role: str = Field(default="viewer", description="admin role: viewer | approver | admin")
    allowed_tenants: list[str] = Field(default_factory=lambda: ["*"])
    claims: list[str] = Field(default_factory=list)


class IssueTokenResponse(BaseModel):
    jti: str
    token: str
    expires_at: datetime
    kind: str
    audience: str


class RevokeRequest(BaseModel):
    reason: str | None = None


def _audit_token_op(
    db: Session,
    caller: CallerContext,
    capability: str,
    args: dict,
    decision: str,
    summary: str,
) -> uuid.UUID:
    audit_id = uuid.uuid4()
    args_hash = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    row = Dispatch(
        audit_id=audit_id,
        trace_id=str(audit_id),
        parent_trace_id=None,
        tenant_id="platform",
        actor_kind="admin",
        actor_id=caller.principal_id,
        actor_tier=3,
        capability=capability,
        args_hash=args_hash,
        args_json=args,
        intent=summary,
        identity_json={
            "logged_in_user": caller.principal_id,
            "session_surface": "admin-api",
            "geopro_target": None,
        },
        decision=decision,
        decision_path="admin-direct",
        decision_reason=None,
        approval_id=None,
        executed_at=datetime.now(UTC),
        result_status="success",
        result_summary=summary,
        latency_ms=0,
        auth_method=caller.auth_method,
    )
    db.add(row)
    return audit_id


@router.post("/admin/issue-token", response_model=IssueTokenResponse, status_code=201)
def issue_token(
    payload: IssueTokenRequest,
    caller: CallerContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> IssueTokenResponse:
    s = get_settings()

    if payload.kind == "admin":
        token, jti = AdminJwtAuth.issue(payload.subject, payload.role, payload.allowed_tenants)
        expires_at = datetime.now(UTC) + timedelta(minutes=s.jwt_admin_ttl_minutes)
        capabilities: list[str] = [payload.role]
    else:
        token, jti = ServiceTokenAuth.issue(
            payload.subject, payload.allowed_tenants, payload.claims
        )
        expires_at = datetime.now(UTC) + timedelta(days=s.jwt_service_ttl_days)
        capabilities = list(payload.claims)

    km = current_signing_key()
    db.add(
        IssuedToken(
            jti=jti,
            issued_by=caller.principal_id,
            kind=payload.kind,
            audience=payload.subject,
            capabilities=capabilities,
            expires_at=expires_at,
            kid=km.kid,
        )
    )
    _audit_token_op(
        db,
        caller,
        capability="sol_issue_token",
        args={
            "kind": payload.kind,
            "subject": payload.subject,
            "role": payload.role,
            "allowed_tenants": payload.allowed_tenants,
            "claims": payload.claims,
        },
        decision="approved",
        summary=f"issued {payload.kind} token for {payload.subject} (jti={jti})",
    )
    db.commit()

    log.info(
        "sol.token.issued",
        jti=jti,
        kind=payload.kind,
        audience=payload.subject,
        issued_by=caller.principal_id,
        kid=km.kid,
    )

    return IssueTokenResponse(
        jti=jti,
        token=token,
        expires_at=expires_at,
        kind=payload.kind,
        audience=payload.subject,
    )


@router.post("/tokens/{jti}/revoke", status_code=200)
def revoke_token(
    jti: str,
    payload: RevokeRequest,
    caller: CallerContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    issued = db.get(IssuedToken, jti)
    if issued is None:
        raise HTTPException(404, detail=f"jti {jti!r} not in issued_tokens")

    existing = db.get(RevokedToken, jti)
    if existing is not None:
        return {
            "jti": jti,
            "revoked_at": existing.revoked_at.isoformat(),
            "already_revoked": True,
        }

    revoked = RevokedToken(jti=jti, revoked_by=caller.principal_id, reason=payload.reason)
    db.add(revoked)

    _audit_token_op(
        db,
        caller,
        capability="sol_revoke_token",
        args={"jti": jti, "reason": payload.reason},
        decision="approved",
        summary=f"revoked jti {jti} (audience={issued.audience}, kind={issued.kind})",
    )
    db.commit()

    # Immediately mark in local cache so this worker stops accepting it.
    add_revoked(jti)

    log.info(
        "sol.token.revoked",
        jti=jti,
        audience=issued.audience,
        kind=issued.kind,
        revoked_by=caller.principal_id,
        reason=payload.reason,
    )

    return {
        "jti": jti,
        "revoked_at": datetime.now(UTC).isoformat(),
        "already_revoked": False,
    }


@router.get("/tokens/issued", status_code=200)
def list_issued(
    caller: CallerContext = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=500),
    kind: str | None = Query(default=None),
    audience: str | None = Query(default=None),
) -> dict[str, object]:
    stmt = select(IssuedToken).order_by(IssuedToken.issued_at.desc()).limit(limit)
    if kind is not None:
        stmt = stmt.where(IssuedToken.kind == kind)
    if audience is not None:
        stmt = stmt.where(IssuedToken.audience == audience)
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "jti": r.jti,
                "issued_at": r.issued_at.isoformat(),
                "issued_by": r.issued_by,
                "kind": r.kind,
                "audience": r.audience,
                "capabilities": r.capabilities,
                "expires_at": r.expires_at.isoformat(),
                "kid": r.kid,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/tokens/revoked", status_code=200)
def list_revoked(
    caller: CallerContext = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=500),
) -> dict[str, object]:
    stmt = select(RevokedToken).order_by(RevokedToken.revoked_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "jti": r.jti,
                "revoked_at": r.revoked_at.isoformat(),
                "revoked_by": r.revoked_by,
                "reason": r.reason,
            }
            for r in rows
        ],
        "count": len(rows),
    }
