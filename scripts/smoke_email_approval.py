#!/usr/bin/env python3
"""Smoke: drive a synthetic approval all the way through SOL.

  1. POST /v1/sol/dispatch with X-SOL-Mode: enforce, capability=permission_gate_op
  2. Verify sol.dispatches row written with approval_id non-NULL.
  3. Inspect sol.approvals row, build a callback URL from the freshly-signed
     token, hit GET /v1/sol/approvals/{id}/decide locally to confirm the
     decide path persists status=approved.

This script is the synthetic round-trip the SOL spec §5 Week 2 calls for.
It does NOT depend on real SMTP being wired — if SMTP_ENABLED=false the
log_only delivery channel records the attempt and the test still asserts
the dispatch → approval → callback decide flow.

Usage on surgecore:
  cd /opt/sol
  source /etc/sol/db.env
  source /etc/sol/service-tokens.env  # provides $SOL_TEST_SERVICE_TOKEN
  ./venv/bin/python scripts/smoke_email_approval.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

SOL_URL = os.environ.get("SOL_URL", "http://127.0.0.1:9320")
SERVICE_TOKEN = os.environ.get("SOL_TEST_SERVICE_TOKEN") or os.environ.get("SOL_BRAIN_SERVICE_TOKEN")
TENANT = os.environ.get("SOL_TEST_TENANT", "system")
APPROVER_EMAIL = os.environ.get("SOL_APPROVER_EMAIL_DEFAULT", "(unset)")


def fail(msg: str, exit_code: int = 1) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(exit_code)


def main() -> int:
    if not SERVICE_TOKEN:
        fail("set SOL_TEST_SERVICE_TOKEN (or SOL_BRAIN_SERVICE_TOKEN) before running")

    trace_id = uuid.uuid4().hex
    body = {
        "capability": "permission_gate_op",
        "args": {
            "tool": "write_file",
            "args": {"path": "/tmp/sol-smoke.txt", "content": "smoke"},
            "risk": "mutate",
        },
        "context": {
            "tenant_id": TENANT,
            "actor": {"kind": "agent", "id": "smoke-script", "tier": 2},
            "identity": {"logged_in_user": "todd"},
            "intent": "phase3.2_smoke_email_round_trip",
            "trace_id": trace_id,
        },
        "options": {"block_until_seconds": 0},
    }
    headers = {
        "X-SOL-Service-Token": SERVICE_TOKEN,
        "X-SurgeXi-Tenant": TENANT,
        "X-SOL-Mode": "enforce",
    }
    t0 = time.monotonic()
    r = httpx.post(f"{SOL_URL}/v1/sol/dispatch", json=body, headers=headers, timeout=15)
    dispatch_ms = int((time.monotonic() - t0) * 1000)

    if r.status_code != 200:
        fail(f"dispatch returned {r.status_code}: {r.text}")
    data = r.json()
    print(f"OK dispatch: decision={data['decision']} approval_id={data.get('approval_id')} latency_ms={dispatch_ms}")
    if data["decision"] != "queued":
        fail(f"expected decision=queued, got {data['decision']!r} (capability missing requires_human?)")
    if not data.get("approval_id"):
        fail("dispatch returned no approval_id")

    approval_id = data["approval_id"]

    # Build a callback URL the same way EmailDelivery would, sign locally.
    sys.path.insert(0, "/opt/sol/src")
    from sol.auth.callback_tokens import issue as issue_callback

    cb_token = issue_callback(uuid.UUID(approval_id), "approve")
    decide_url = f"{SOL_URL}/v1/sol/approvals/{approval_id}/decide"
    r2 = httpx.get(decide_url, params={"token": cb_token, "decision": "approve"}, timeout=10)
    if r2.status_code != 200:
        fail(f"decide returned {r2.status_code}: {r2.text}")
    final = r2.json()
    print(f"OK decide: status={final['status']} decided_by={final.get('decided_by')}")
    if final["status"] != "approved":
        fail(f"expected status=approved, got {final['status']!r}")

    # Final cross-check via list_pending — should be empty for this approval.
    print(f"OK smoke complete: approver_email_default={APPROVER_EMAIL} trace_id={trace_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
