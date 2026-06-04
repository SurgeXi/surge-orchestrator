"""POST /v1/sol/dispatch — single entry point for every side-effect.

Week 1: shadow-only path. Every dispatch writes an audit row and returns
decision="shadow". No downstream execution. Enforce path lands Week 6.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Dispatch
from ..observability.logging import get_logger
from ..observability.metrics import dispatch_latency_seconds, dispatches_total
from ..schemas.dispatch import DispatchRequest, DispatchResponse
from ..settings import get_settings
from .deps import CallerContext, get_caller

router = APIRouter()
log = get_logger(__name__)


def _canonical_args_hash(args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.post("/dispatch", response_model=DispatchResponse, status_code=200)
def dispatch(
    payload: DispatchRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
) -> DispatchResponse:
    s = get_settings()
    started = time.monotonic()

    # tenant guard
    ctx_tenant = payload.context.tenant_id
    if (
        caller.principal_kind in ("service", "mtls")
        and ctx_tenant not in caller.allowed_tenants
        and "*" not in caller.allowed_tenants
    ):
        raise HTTPException(403, detail="actor not permitted for tenant")

    audit_id = uuid.uuid4()
    args_hash = _canonical_args_hash(payload.args)

    # Phase 3.1 Week 1 — every path is shadow regardless of header value.
    # SOL_ENFORCE is false in Week 1 deploy. Header X-SOL-Mode: shadow is the
    # explicit shadow signal from the upstream hook; absence is treated as
    # shadow in this build until enforcement lands Week 6.
    shadow_mode = True if s.is_shadow_only else caller.shadow_mode

    decision = "shadow" if shadow_mode else "deferred"
    decision_path = "shadow-bypass" if shadow_mode else "auto-policy"
    reason = "shadow_only_phase31_week1" if shadow_mode else None

    row = Dispatch(
        audit_id=audit_id,
        trace_id=payload.context.trace_id,
        parent_trace_id=payload.context.parent_trace_id,
        tenant_id=ctx_tenant,
        actor_kind=payload.context.actor.kind,
        actor_id=payload.context.actor.id,
        actor_tier=payload.context.actor.tier,
        capability=payload.capability,
        args_hash=args_hash,
        args_json=payload.args,
        intent=payload.context.intent,
        identity_json=payload.context.identity.model_dump(),
        decision=decision,
        decision_path=decision_path,
        decision_reason=reason,
        approval_id=None,
        executed_at=None,
        result_status=None,
        result_summary=None,
        latency_ms=None,
        auth_method=caller.auth_method,
    )
    db.add(row)
    db.commit()

    elapsed = time.monotonic() - started
    dispatch_latency_seconds.labels(
        tenant=ctx_tenant, capability=payload.capability
    ).observe(elapsed)
    dispatches_total.labels(
        tenant=ctx_tenant, capability=payload.capability, decision=decision
    ).inc()

    log.info(
        "sol.dispatch.shadow" if shadow_mode else "sol.dispatch",
        audit_id=str(audit_id),
        trace_id=payload.context.trace_id,
        tenant=ctx_tenant,
        capability=payload.capability,
        actor=payload.context.actor.id,
        actor_tier=payload.context.actor.tier,
        decision=decision,
        auth_method=caller.auth_method,
        client_cn=caller.principal_id if caller.principal_kind == "mtls" else None,
        latency_ms=int(elapsed * 1000),
    )

    return DispatchResponse(
        decision=decision,
        audit_id=audit_id,
        trace_id=payload.context.trace_id,
        result=None,
        approval_id=None,
        decision_path=decision_path,
        decision_reason=reason,
    )
