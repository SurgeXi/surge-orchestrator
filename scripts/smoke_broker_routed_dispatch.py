#!/usr/bin/env python3
# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Phase 3.3 Week 3 smoke — drive a real broker capability via SOL.

End-to-end:
   client -> POST /v1/sol/dispatch (X-SOL-Mode: enforce)
   SOL    -> insert sol.dispatches row, decision=approved (auto-policy)
   SOL    -> POST broker :8220/v1/surge/dispatch with X-SOL-Bypass: true
   Broker -> validate + execute capability (bypasses internal approval)
   SOL    -> writes executed_at + result_status + result_summary on the row
   SOL    -> returns DispatchResponse(decision="approved", result={...})

Run on surgecore. Reads SOL service token from /etc/sol/tokens/brain.service-token
(or override via SOL_SMOKE_TOKEN_PATH). Defaults to the read-only db_query
capability so the smoke can never mutate state.

Usage:
   sudo -u sol /opt/sol/venv/bin/python \\
     /opt/sol/scripts/smoke_broker_routed_dispatch.py [capability] [json-params]

Exit codes:
   0  approved + executor success
   1  unexpected SOL response
   2  executor returned non-success
   3  HTTP transport failure
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

SOL_BASE = os.environ.get("SOL_BASE_URL", "http://127.0.0.1:9320")
TOKEN_PATH = os.environ.get(
    "SOL_SMOKE_TOKEN_PATH", "/etc/sol/tokens/brain.service-token"
)


def _load_token() -> str:
    with open(TOKEN_PATH, encoding="utf-8") as f:
        return f.read().strip()


def main() -> int:
    target_cap = sys.argv[1] if len(sys.argv) > 1 else "db_query"
    if len(sys.argv) > 2:
        params = json.loads(sys.argv[2])
    else:
        params = {"sql": "select 1 as one", "limit": 1}

    token = _load_token()
    trace_id = f"phase33-smoke-{uuid.uuid4().hex[:12]}"
    payload = {
        "capability": "broker_capability",
        "args": {
            "target": target_cap,
            "params": params,
            "timeout_s": 60,
        },
        "context": {
            "tenant_id": "system",
            "actor": {"kind": "agent", "id": "phase33-smoke", "tier": 2},
            "identity": {"logged_in_user": "todd"},
            "intent": f"smoke:{target_cap}",
            "trace_id": trace_id,
        },
        "options": {"block_until_seconds": 60},
    }

    print(f"--> POST {SOL_BASE}/v1/sol/dispatch capability={target_cap}")
    try:
        resp = httpx.post(
            f"{SOL_BASE}/v1/sol/dispatch",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-SOL-Mode": "enforce",
                "X-SurgeXi-Tenant": "system",
                "Content-Type": "application/json",
            },
            timeout=90.0,
        )
    except httpx.HTTPError as e:
        print(f"!! transport failure: {type(e).__name__}: {e}")
        return 3

    print(f"<-- HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        print(f"!! non-JSON response: {resp.text[:400]}")
        return 1
    print(json.dumps(body, indent=2, default=str))
    if resp.status_code >= 400:
        return 1

    decision = body.get("decision")
    decision_path = body.get("decision_path")
    audit_id = body.get("audit_id")
    print(
        f"== decision={decision} path={decision_path} audit_id={audit_id} "
        f"trace_id={trace_id}"
    )
    if decision not in ("approved", "executed"):
        print(f"!! unexpected decision: {decision}")
        return 1
    result = body.get("result") or {}
    if result.get("status") != "success":
        print(f"!! executor result.status={result.get('status')}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
