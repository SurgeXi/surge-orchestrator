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

The full policy engine + tier learning slots in Week 3-5 between the
"needs human?" check and the executor dispatch.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..executors.broker import execute_broker
from ..models import Capability, Dispatch
from ..observability.logging import get_logger
from ..observability.metrics import dispatch_latency_seconds, dispatches_total
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


# ---- Auto-readonly lane: Surge autonomy for provably read-only host ops ----
# A run_bash whose command is a single pipeline of allow-listed read-only
# binaries with NO redirect / substitution / backgrounding / chaining /
# network / find-write-action. Allow-list, not deny-list; fail CLOSED on any
# ambiguity. awk/sed/xargs/env are EXCLUDED (can write or exec without a
# shell redirect). The systemd sandbox remains the hard floor underneath.
_READONLY_BINARIES = frozenset({
    "find", "ls", "stat", "du", "df", "cat", "head", "tail", "wc", "grep",
    "egrep", "fgrep", "zgrep", "sort", "uniq", "cut", "file", "sha256sum",
    "md5sum", "echo", "printf", "tr", "nl", "basename", "dirname", "realpath",
    "readlink", "pwd", "whoami", "uname", "free", "uptime",
    "column", "comm", "tac", "rev", "jq", "tree", "id",
})
# NOTE: `date` and `hostname` are intentionally NOT allow-listed. Both have
# state-changing invocations (`date -s/--set` sets the clock; `hostname NAME`
# / `hostname -b` sets the hostname). Their read value is covered by
# uname/uptime/free, so we fail CLOSED rather than try to distinguish their
# read vs write forms.
_READONLY_FORBIDDEN_FLAGS = frozenset({
    "-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls",
})
# Per-binary write/state-change flags. Each entry: (short_letters, long_flags).
#   short_letters: single chars that, if present in ANY combined short-flag
#     bundle (a token like `-rno` or `-o/tmp/x`), mean a write -> reject.
#   long_flags: `--name` forms; reject if token == it or starts with `--name=`.
# This catches glued (`-o/tmp/x`), `--output=FILE`, separated (`-o /tmp/x`),
# combined (`-rno FILE`), quoted, pipeline-stage, and abs-path forms alike.
_BINARY_WRITE_FLAGS = {
    "sort": (frozenset({"o"}), ("--output",)),
}


def classify_readonly(payload_args: dict) -> bool:
    """True only for a run_bash whose command is provably read-only: a pipeline
    of allow-listed read-only binaries with no redirect, command substitution,
    backgrounding, chaining, or find/-exec-style write action. Fail CLOSED."""
    try:
        if str(payload_args.get("tool", "")) != "run_bash":
            return False
        cmd = (payload_args.get("args", {}) or {}).get("cmd", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return False
        if any(t in cmd for t in (">", "<", "`", "$(", "${", "&", ";", "\n", "\r")):
            return False
        for segment in cmd.split("|"):
            try:
                toks = shlex.split(segment)
            except ValueError:
                return False
            if not toks:
                return False
            binary = toks[0].rsplit("/", 1)[-1]
            if binary not in _READONLY_BINARIES:
                return False
            short_writes, long_writes = _BINARY_WRITE_FLAGS.get(
                binary, (frozenset(), ())
            )
            for t in toks:
                if t in _READONLY_FORBIDDEN_FLAGS or t.startswith("-exec"):
                    return False
                # Per-binary write-flag denylist (e.g. `sort -o FILE`).
                if t.startswith("--"):
                    head = t.split("=", 1)[0]
                    if head in long_writes:
                        return False
                elif t.startswith("-") and len(t) > 1 and short_writes:
                    # Combined short-flag bundle: reject if any write letter
                    # appears before its (possibly glued) argument. Scan the
                    # cluster up to the first non-flag char of a value.
                    if any(ch in short_writes for ch in t[1:]):
                        return False
        return True
    except Exception:
        return False


@router.post("/dispatch", response_model=DispatchResponse, status_code=200)
def dispatch(
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

    # Auto-readonly lane: a provably read-only run_bash that would otherwise be
    # human-gated is auto-approved. Mutating/remote/deploy work stays gated.
    auto_readonly = False
    if needs_human and s.auto_readonly and classify_readonly(payload.args):
        needs_human = False
        auto_readonly = True

    # ---------- audit row written for EVERY dispatch ----------
    decision = "shadow"
    decision_path = "shadow-bypass"
    reason: str | None = "shadow_only_phase31_week1" if shadow_mode else None
    approval_id: uuid.UUID | None = None

    if not shadow_mode:
        if needs_human:
            decision = "queued"
            decision_path = "human-approval"
            reason = "requires_human"
        else:
            if auto_readonly:
                decision = "approved"
                decision_path = "auto-readonly"
                reason = "readonly_allowlisted"
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

    if not shadow_mode and needs_human:
        # Create approval + fan out delivery. Sync wrapper around the
        # async service for the sync FastAPI handler — Python 3.12's
        # ``asyncio.run`` is fine because dispatch handlers are sync.
        import asyncio

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

    # ---------- Phase 3.3: forward approved broker dispatches ----------
    # When the dispatch's capability is one of the broker-handled ones
    # and the decision came out APPROVED (auto-policy or human-approved
    # callback), forward to Broker's executor and record the result on
    # the audit row. DENIED / QUEUED outcomes do NOT execute.
    executor_result: DispatchResult | None = None
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
            from datetime import datetime, timezone

            row.executed_at = datetime.now(tz=timezone.utc)
            row.result_status = outcome
            row.result_summary = summary
            db.commit()
            executor_result = DispatchResult(
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
        result=executor_result,
        approval_id=approval_id,
        decision_path=decision_path,
        decision_reason=reason,
    )
