"""POST /v1/sol/dispatch — single entry point for every side-effect.

Phase 3.2 Week 2 modes:
  - shadow:  audit-only; never creates approvals or runs executors.
  - enforce: when the capability (or its risk band) requires human,
             SOL creates a sol.approvals row, dispatches delivery
             channels, and blocks (up to ``block_until_seconds``) for
             a decision. Returns decision=approved/denied/queued.

Mode source of truth (in order):
  1. X-SOL-Mode header from the caller ("shadow" | "enforce").
  2. Settings.enforce — when true and shadow_enabled is false, every
     call without an explicit header is treated as enforce. (Week 1
     deploy has enforce=false.)

Decision policy (Week 2 — pre-policy-engine):
  - If sol.capabilities row sets requires_human=true → human approval.
  - Else if args.risk ∈ {mutate, remote, destructive} → human approval.
  - Else → auto-approved.

Cross-rule evaluation (Phase 3.4 Week 4):
  - Before deciding requires-human/auto, evaluate cross-rule
    constraints (e.g. ``repo_cooldown``) against recent dispatch
    history. A cross-rule denial wins immediately — no approval is
    created, no executor is called.

Executor dispatch (Phase 3.4 Week 4):
  - When the final decision is ``approved`` (auto or human),
    SOL invokes the executor registered for the capability's
    ``handler_kind``. Result is recorded back into the dispatches
    row (``result_status``, ``result_summary``, ``executed_at``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..executors.broker import execute_broker
from ..executors.surge_runner import execute_runner
from ..models import Capability, Dispatch
from ..observability.logging import get_logger
from ..observability.metrics import dispatch_latency_seconds, dispatches_total
from ..policy.cross_rules import evaluate_repo_cooldown
from ..schemas.dispatch import DispatchRequest, DispatchResponse, DispatchResult
from ..services.approvals import create_and_deliver, poll_for_decision
from ..settings import get_settings
from .deps import CallerContext, get_caller

router = APIRouter()
log = get_logger(__name__)

# Risk bands that force a human approval even when the capability row
# doesn't set requires_human. Mirrors brain/tools.py risk constants so
# Brain's existing tool-call payloads (which carry args["risk"]) need
# no translation here.
_HUMAN_RISK_BANDS = {"mutate", "remote", "destructive"}

# Capability rows whose handler_kind == "broker". When SOL picks a
# decision of approved / human-approved-callback for one of these caps,
# we forward to the broker executor and capture the result on the row.
_BROKER_CAPABILITIES = {"broker_capability", "broker_dispatch"}


def _canonical_args_hash(args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _needs_human(cap: Capability | None, args: dict) -> bool:
    if cap is not None and bool(getattr(cap, "requires_human", False)):
        return True
    risk = str(args.get("risk", "") or "").strip().lower()
    return risk in _HUMAN_RISK_BANDS


@router.post("/dispatch", response_model=DispatchResponse, status_code=200)
def dispatch(
    request: Request,
    payload: DispatchRequest,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
) -> DispatchResponse:
    s = get_settings()
    started = time.monotonic()

    ctx_tenant = payload.context.tenant_id
    if (
        caller.principal_kind == "service"
        and ctx_tenant not in caller.allowed_tenants
        and "*" not in caller.allowed_tenants
    ):
        raise HTTPException(403, detail="actor not permitted for tenant")

    audit_id = uuid.uuid4()
    args_hash = _canonical_args_hash(payload.args)

    # Mode resolution.
    shadow_mode = bool(caller.shadow_mode)
    if not caller.shadow_mode and s.is_shadow_only:
        # No explicit enforce signal AND global shadow_only flag is on.
        shadow_mode = True

    cap = db.get(Capability, payload.capability)
    needs_human = _needs_human(cap, payload.args)

    # ---------- cross-rule evaluation (Phase 3.4) ----------
    # Cross-rules run BEFORE approval / executor for non-shadow paths.
    # A denial here short-circuits — no approval row, no executor call.
    cross_denied = False
    cross_reason: str | None = None
    cross_rule_name: str | None = None
    if not shadow_mode:
        cache = getattr(request.app.state, "policy_cache", None)
        if cache is not None:
            cr = evaluate_repo_cooldown(
                db=db,
                capability=payload.capability,
                tenant_id=ctx_tenant,
                args=payload.args or {},
                cache=cache,
            )
            if not cr.allowed:
                cross_denied = True
                cross_reason = cr.reason
                cross_rule_name = cr.rule

    # ---------- audit row written for EVERY dispatch ----------
    decision = "shadow"
    decision_path = "shadow-bypass"
    reason: str | None = "shadow_only_phase31_week1" if shadow_mode else None
    approval_id: uuid.UUID | None = None

    if not shadow_mode:
        if cross_denied:
            decision = "denied"
            decision_path = f"cross-rule-{cross_rule_name or 'deny'}"
            reason = cross_reason
        elif needs_human:
            decision = "queued"
            decision_path = "human-approval"
            reason = "requires_human"
        else:
            decision = "approved"
            decision_path = "auto-policy"
            reason = "auto_under_threshold"

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
        auth_method=getattr(caller, "auth_method", None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    dispatch_pk = row.id

    if not shadow_mode and not cross_denied and needs_human:
        # Create approval + fan out delivery. Sync wrapper around the
        # async service for the sync FastAPI handler — Python 3.12's
        # ``asyncio.run`` is fine because dispatch handlers are sync.
        approval = asyncio.run(
            create_and_deliver(
                db=db,
                dispatch_id=dispatch_pk,
                trace_id=payload.context.trace_id,
                tenant_id=ctx_tenant,
                actor_kind=payload.context.actor.kind,
                actor_id=payload.context.actor.id,
                capability=payload.capability,
                args_json=payload.args,
                intent=payload.context.intent,
                ttl_seconds=max(payload.options.block_until_seconds, 600),
            )
        )
        approval_id = approval.id
        row.approval_id = approval_id
        db.commit()

        # Block up to the caller's budget for a human decision.
        block_s = max(0, min(int(payload.options.block_until_seconds), 600))
        if block_s > 0:
            final_row = poll_for_decision(db, approval_id, block_s)
            if final_row is not None and final_row.status in ("approved", "denied"):
                decision = final_row.status
                decision_path = f"human-{final_row.status}-callback"
                reason = final_row.decision_reason or final_row.status
                row.decision = decision
                row.decision_path = decision_path
                row.decision_reason = reason
                db.commit()

    # ---------- executor dispatch (Phase 3.3 + 3.4) ----------
    # When decision is "approved" (auto-policy OR human-approval-callback)
    # we route to the appropriate executor. Two paths:
    #   - Phase 3.3: broker dispatch by capability name (broker_capability,
    #     broker_dispatch). Wraps Broker /v1/surge/dispatch with bypass.
    #   - Phase 3.4: surge-runner dispatch by cap.handler_kind == 'surge_runner'.
    # The two paths are non-overlapping; broker caps don't carry the
    # surge_runner handler_kind. DENIED / QUEUED outcomes do NOT execute.
    result: DispatchResult | None = None

    # ---------- Phase 3.3: forward approved broker dispatches ----------
    if (
        not shadow_mode
        and payload.capability in _BROKER_CAPABILITIES
        and decision == "approved"
    ):
        target_cap = str(payload.args.get("target") or "").strip()
        target_params = payload.args.get("params") or {}
        if not target_cap:
            row.result_status = "error"
            row.result_summary = "broker dispatch missing args.target"
            db.commit()
        else:
            br = execute_broker(
                target_cap,
                target_params if isinstance(target_params, dict) else {},
                tenant_id=ctx_tenant,
                actor_id=payload.context.actor.id,
                trace_id=payload.context.trace_id,
                timeout_s=float(payload.args.get("timeout_s") or 0) or None,
            )
            outcome = str(br.get("outcome") or "error")
            summary = str(br.get("summary") or "")[:1024]
            row.executed_at = datetime.now(tz=UTC)
            row.result_status = outcome
            row.result_summary = summary
            db.commit()
            result = DispatchResult(
                status=outcome,
                summary=summary or None,
                stdout=None,
                stderr=None,
                exit_code=None,
                data=br.get("data") if isinstance(br.get("data"), dict) else None,
                broker_audit_id=(
                    str(br.get("audit_id")) if br.get("audit_id") else None
                ),
                capability=target_cap,
            )
            # Surface the broker's full payload back to the caller so
            # Brain's surge_invoke can pass it to the agent loop unchanged.
            # We stash it under result_summary if small; the full dict
            # rides on the response model only (we keep result_summary
            # a short string for SQL friendliness).
            log.info(
                "sol.executor.broker.routed target=%s outcome=%s tenant=%s",
                target_cap,
                outcome,
                ctx_tenant,
            )

    # ---------- Phase 3.4: surge-runner executor ----------
    if (
        not shadow_mode
        and decision == "approved"
        and cap is not None
        and result is None
    ):
        handler_kind = getattr(cap, "handler_kind", None)
        if handler_kind == "surge_runner":
            exec_started = time.monotonic()
            try:
                exec_result = asyncio.run(
                    execute_runner(payload.capability, payload.args or {})
                )
            except Exception as e:  # pragma: no cover - defensive
                log.exception("sol.dispatch.executor_crash", capability=payload.capability)
                exec_result = {
                    "status": "error",
                    "stdout": None,
                    "stderr": f"{type(e).__name__}: {e}",
                    "exit_code": 99,
                    "summary": "executor crash",
                }
            exec_elapsed_ms = int((time.monotonic() - exec_started) * 1000)
            row.executed_at = datetime.now(UTC)
            row.result_status = exec_result.get("status")
            row.result_summary = exec_result.get("summary")
            row.latency_ms = exec_elapsed_ms
            if exec_result.get("status") == "success":
                decision = "executed"
                decision_path = decision_path + "+executed"
                row.decision = decision
                row.decision_path = decision_path
            else:
                # Executor failure — leave decision="approved" but record
                # the result so the audit row tells the full story. The
                # response decision below reflects the executor outcome
                # via the result.status field.
                decision_path = decision_path + "+executor-error"
                row.decision_path = decision_path
            db.commit()
            try:
                result = DispatchResult(**exec_result)
            except Exception:  # pragma: no cover - schema fallback
                result = DispatchResult(
                    status=str(exec_result.get("status") or "error"),
                    summary=str(exec_result.get("summary") or ""),
                )

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
        decision_path=decision_path,
        approval_id=str(approval_id) if approval_id else None,
        latency_ms=int(elapsed * 1000),
    )

    return DispatchResponse(
        decision=decision,
        audit_id=audit_id,
        trace_id=payload.context.trace_id,
        result=result,
        approval_id=approval_id,
        decision_path=decision_path,
        decision_reason=reason,
    )
