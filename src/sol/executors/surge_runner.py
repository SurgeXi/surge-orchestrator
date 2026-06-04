"""Surge Runner executor — forwards approved dispatches to surge-runner.

Phase 3.4 Week 4 — per SOL spec §5.

Routes the ``surge_runner_dispatch`` capability (and any handler_kind=
``surge_runner`` capability) to the Surge Runner API at
``http://<runner-host>:9100/tasks``. SOL has already evaluated rate
limit, tenant isolation, tier, repo cooldown, and (for requires_human
capabilities) human approval — this executor performs the side-effect.

Configuration:
  - ``SOL_SURGE_RUNNER_BASE_URL`` — default ``http://100.107.52.93:9100``
    (Tailscale IP of surge-ai, matches the legacy curator default).
  - ``SOL_SURGE_RUNNER_TOKEN_PATH`` — default
    ``/etc/sol/runner-callers/surge-runner-api.token``. File MUST be
    mode 0640 root:todds and contain the bearer token surge-runner's
    ``/tasks`` endpoint expects.
  - ``SOL_SURGE_RUNNER_TIMEOUT_S`` — request timeout (default 15s).

Args contract (passed through from the dispatch payload):
  - ``prompt`` (required) — the issue payload Surge will execute on.
  - ``system_prompt`` (optional) — runner system prompt override.
  - ``source`` (optional) — dispatch origin tag (default "sol-dispatch").
  - ``external_id`` (optional) — runner-side de-dupe key.
  - ``metadata`` (optional dict) — runner-side metadata.
  - ``max_steps`` (optional int) — runner step cap.
  - ``allowed_ssh_hosts`` / ``allowed_http_hosts`` /
    ``allowed_write_prefixes`` (optional lists).

Return shape matches ``sol.schemas.dispatch.DispatchResult``:
  - ``status`` — "success" | "error"
  - ``stdout`` — JSON of runner's response body on success (capped)
  - ``stderr`` — error string on failure (capped)
  - ``exit_code`` — 0 on success, non-zero on error
  - ``summary`` — short human-readable line for the audit row
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from ..observability.logging import get_logger

log = get_logger(__name__)

_DEFAULT_BASE_URL = "http://100.107.52.93:9100"
_DEFAULT_TOKEN_PATH = "/etc/sol/runner-callers/surge-runner-api.token"
_DEFAULT_TIMEOUT_S = 15.0
_MAX_CAPTURE_BYTES = 4096


def _base_url() -> str:
    return os.environ.get("SOL_SURGE_RUNNER_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _token_path() -> str:
    return os.environ.get("SOL_SURGE_RUNNER_TOKEN_PATH", _DEFAULT_TOKEN_PATH)


def _timeout_s() -> float:
    raw = os.environ.get("SOL_SURGE_RUNNER_TIMEOUT_S")
    if raw is None:
        return _DEFAULT_TIMEOUT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def _load_token() -> str | None:
    p = Path(_token_path())
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _cap(s: str | None) -> str | None:
    if s is None:
        return None
    if len(s) > _MAX_CAPTURE_BYTES:
        return s[: _MAX_CAPTURE_BYTES - 12] + "…[truncated]"
    return s


def _build_runner_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Map the dispatch ``args`` dict to the runner ``/tasks`` schema.

    Any keys the runner doesn't understand are dropped silently rather
    than passed through, so a malformed dispatch from a caller can't
    poison the runner's request validator. The runner's own request
    schema is the second line of defence — this function exists so SOL
    can reason about what it's forwarding.
    """
    out: dict[str, Any] = {}
    if "prompt" in args:
        out["prompt"] = args["prompt"]
    if "system_prompt" in args:
        out["system_prompt"] = args["system_prompt"]
    out["source"] = args.get("source") or "sol-dispatch"
    if "external_id" in args:
        out["external_id"] = args["external_id"]
    if "metadata" in args and isinstance(args["metadata"], dict):
        out["metadata"] = args["metadata"]
    if "max_steps" in args:
        out["max_steps"] = args["max_steps"]
    for k in ("allowed_ssh_hosts", "allowed_http_hosts", "allowed_write_prefixes"):
        if k in args and isinstance(args[k], list):
            out[k] = args[k]
    return out


async def execute_runner(capability: str, args: dict[str, Any]) -> dict[str, Any]:
    """Forward the call to surge-runner's POST /tasks.

    Returns a DispatchResult-shaped dict — see module docstring.
    """
    token = _load_token()
    if not token:
        log.warning(
            "surge_runner.executor.missing_token",
            capability=capability,
            token_path=_token_path(),
        )
        return {
            "status": "error",
            "stdout": None,
            "stderr": f"surge-runner token missing at {_token_path()}",
            "exit_code": 2,
            "summary": "surge-runner token missing",
        }

    if "prompt" not in args or not args.get("prompt"):
        return {
            "status": "error",
            "stdout": None,
            "stderr": "missing required arg: prompt",
            "exit_code": 22,
            "summary": "missing prompt",
        }

    payload = _build_runner_payload(args)
    url = f"{_base_url()}/tasks"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_timeout_s()) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        log.warning(
            "surge_runner.executor.timeout",
            capability=capability,
            url=url,
            error=str(e),
        )
        return {
            "status": "error",
            "stdout": None,
            "stderr": _cap(f"timeout: {e!r}"),
            "exit_code": 124,
            "summary": "surge-runner timeout",
        }
    except httpx.HTTPError as e:
        log.warning(
            "surge_runner.executor.network",
            capability=capability,
            url=url,
            error=str(e),
        )
        return {
            "status": "error",
            "stdout": None,
            "stderr": _cap(f"network: {type(e).__name__}: {e}"),
            "exit_code": 1,
            "summary": "surge-runner network error",
        }

    body_text = resp.text or ""
    if resp.status_code >= 400:
        log.warning(
            "surge_runner.executor.http_error",
            capability=capability,
            status_code=resp.status_code,
            body=_cap(body_text),
        )
        return {
            "status": "error",
            "stdout": _cap(body_text),
            "stderr": _cap(f"HTTP {resp.status_code}"),
            "exit_code": resp.status_code,
            "summary": f"surge-runner HTTP {resp.status_code}",
        }

    try:
        parsed = resp.json()
    except (ValueError, json.JSONDecodeError):
        parsed = {}

    task_id = parsed.get("id") if isinstance(parsed, dict) else None
    log.info(
        "surge_runner.executor.dispatched",
        capability=capability,
        task_id=task_id,
        status_code=resp.status_code,
    )
    return {
        "status": "success",
        "stdout": _cap(body_text),
        "stderr": None,
        "exit_code": 0,
        "summary": (
            f"surge-runner accepted task_id={task_id}"
            if task_id
            else f"surge-runner accepted (HTTP {resp.status_code})"
        ),
    }
