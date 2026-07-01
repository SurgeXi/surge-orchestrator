# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Broker executor — forwards to Maestro Broker :8220 (Phase 3.3 Week 3).

Wires SOL's dispatch path to Broker's existing
``POST /v1/surge/dispatch`` capability endpoint.

Trust model
-----------
SOL holds the policy decision; Broker becomes a thin executor. SOL
authenticates to Broker with the operator service-token (already used
by Brain today) and asserts the policy decision via the
``X-SOL-Bypass`` header. Broker, when launched with
``SOL_BROKER_BYPASS=true``, treats that header as proof that SOL has
already gated the request, and skips its own
``_persist_pending`` / ntfy approval fan-out. Validation, audit, and
executor work all still run inside Broker.

Failure modes
-------------
Any transport failure, HTTP 4xx/5xx, or non-dict body is surfaced as
a ``DispatchResult``-shaped dict with ``outcome="error"`` so the
SOL dispatch handler can record ``result_status`` cleanly without
raising. The handler stays sync; this module uses ``httpx``'s sync
client.

Configuration (env, SOL_-prefixed via Settings)
-----------------------------------------------
SOL_BROKER_URL                 (default http://127.0.0.1:8220)
SOL_BROKER_API_TOKEN_PATH      (default /etc/sol/tokens/broker-api.token)
SOL_BROKER_DISPATCH_TIMEOUT_S  (default 120)

If the token file is missing or empty the executor returns an error
result; it never falls back to an unauthenticated call.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("sol.executors.broker")


def _env_or(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val.strip() if val else default


def _read_token() -> str | None:
    path = _env_or("SOL_BROKER_API_TOKEN_PATH", "/etc/sol/tokens/broker-api.token")
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        return tok or None
    except OSError:
        return None


def _error(target: str, summary: str) -> dict[str, Any]:
    return {
        "outcome": "error",
        "summary": summary,
        "data": None,
        "audit_id": None,
        "approval_id": None,
        "capability": target,
    }


def execute_broker(
    target_capability: str,
    params: dict[str, Any],
    *,
    tenant_id: str | None = None,
    actor_id: str | None = None,
    trace_id: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """POST ``/v1/surge/dispatch`` on Broker. Returns the broker's
    ``DispatchResult`` dict (outcome / summary / data / audit_id / capability).

    Never raises. Synchronous on purpose so the existing sync dispatch
    handler can call us under ``asyncio.run`` from the same code path
    that drives ``create_and_deliver`` for human-approval flows.
    """
    base_url = _env_or("SOL_BROKER_URL", "http://127.0.0.1:8220").rstrip("/")
    token = _read_token()
    if not token:
        return _error(
            target_capability,
            "sol broker executor: api token missing or unreadable",
        )

    try:
        timeout_default = float(_env_or("SOL_BROKER_DISPATCH_TIMEOUT_S", "120"))
    except ValueError:
        timeout_default = 120.0
    t = float(timeout_s) if timeout_s else timeout_default
    # Cap: Brain agent loop wall-clock has a hard ceiling and we should
    # never block longer than the broker side will run.
    t = max(1.0, min(t, 300.0))

    body: dict[str, Any] = {"capability": target_capability, "params": params or {}}
    if tenant_id:
        body["tenant_id"] = tenant_id

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        # Proof-of-policy assertion. Broker recognises this header only
        # when SOL_BROKER_BYPASS=true is set on its environment, so the
        # bypass cannot be triggered by an unauthorised caller.
        "X-SOL-Bypass": "true",
        "User-Agent": "sol-broker-executor/1.0",
    }
    if trace_id:
        headers["X-SOL-Trace-Id"] = trace_id
    if actor_id:
        headers["X-SOL-Actor"] = actor_id

    started = time.monotonic()
    try:
        import httpx
    except Exception as e:
        return _error(
            target_capability,
            f"sol broker executor: httpx import failed: {type(e).__name__}: {e}",
        )

    url = f"{base_url}/v1/surge/dispatch"
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=t)
    except httpx.HTTPError as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        log.warning(
            "sol broker executor transport failure: %s in %d ms",
            type(e).__name__,
            elapsed_ms,
        )
        return _error(
            target_capability,
            f"broker_unreachable: {type(e).__name__}: {e}",
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return _error(
            target_capability,
            f"broker HTTP {resp.status_code}: non-JSON body",
        )

    if resp.status_code >= 400:
        detail = None
        if isinstance(data, dict):
            detail = data.get("detail") or data.get("summary")
        return _error(
            target_capability,
            f"broker HTTP {resp.status_code}: {detail!r}",
        )

    if not isinstance(data, dict):
        return _error(target_capability, "broker returned non-dict body")

    # Normal path: broker already speaks DispatchResult.
    data.setdefault("capability", target_capability)
    log.info(
        "sol.executor.broker outcome=%s capability=%s tenant=%s elapsed_ms=%d",
        data.get("outcome"),
        target_capability,
        tenant_id,
        elapsed_ms,
    )
    return data
