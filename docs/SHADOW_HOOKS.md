# SOL shadow hooks — calling-agent integration

Every fleet agent that emits a side-effect calls SOL's `POST /v1/sol/dispatch` with `X-SOL-Mode: shadow`. SOL writes an audit row and returns `decision=shadow`. The agent's legacy path runs unchanged. Failure to reach SOL is logged but does NOT block.

## Reference Python helper

`shadow_hook.py` (drop-in for Brain `/opt/surgexi/brain/`, Broker, Surge Runner):

```python
import asyncio
import os
import httpx
import logging
import uuid

log = logging.getLogger("sol_shadow")

SOL_URL = os.environ.get("SOL_URL", "http://127.0.0.1:9320")
SOL_SHADOW_ENABLED = os.environ.get("SOL_SHADOW_ENABLED", "true").lower() == "true"
SOL_SHADOW_TIMEOUT_MS = int(os.environ.get("SOL_SHADOW_TIMEOUT_MS", "50"))
SOL_SERVICE_TOKEN = os.environ.get("SOL_SERVICE_TOKEN", "")
AGENT_NAME = os.environ.get("SOL_AGENT_NAME", "unknown")
AGENT_TIER = int(os.environ.get("SOL_AGENT_TIER", "2"))

_client: httpx.AsyncClient | None = None


def _client_singleton() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=SOL_URL,
            timeout=httpx.Timeout(SOL_SHADOW_TIMEOUT_MS / 1000.0),
        )
    return _client


async def shadow_emit(
    capability: str,
    args: dict,
    tenant_id: str = "platform",
    actor_kind: str = "agent",
    intent: str | None = None,
    trace_id: str | None = None,
    parent_trace_id: str | None = None,
    identity: dict | None = None,
) -> None:
    if not SOL_SHADOW_ENABLED:
        return
    payload = {
        "capability": capability,
        "args": args,
        "context": {
            "tenant_id": tenant_id,
            "actor": {"kind": actor_kind, "id": AGENT_NAME, "tier": AGENT_TIER},
            "identity": identity or {},
            "intent": intent,
            "trace_id": trace_id or str(uuid.uuid4()),
            "parent_trace_id": parent_trace_id,
        },
        "options": {"block_until_seconds": 0},
    }
    headers = {
        "X-SOL-Mode": "shadow",
        "X-SurgeXi-Tenant": tenant_id,
    }
    if SOL_SERVICE_TOKEN:
        headers["X-SOL-Service-Token"] = SOL_SERVICE_TOKEN
    try:
        client = _client_singleton()
        await client.post("/v1/sol/dispatch", json=payload, headers=headers)
    except Exception as e:
        log.warning("sol_shadow_failed: %s", e)


def shadow_emit_sync(*args, **kwargs):
    """Fire-and-forget wrapper for sync code paths."""
    if not SOL_SHADOW_ENABLED:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(shadow_emit(*args, **kwargs))
        else:
            loop.run_until_complete(shadow_emit(*args, **kwargs))
    except Exception as e:
        log.warning("sol_shadow_sync_failed: %s", e)
```

## Brain integration (`/opt/surgexi/brain/tools.py`)

Two install points:

1. Inside `call_tool(tool_name, args)` — right before the actual `permission_gate.enqueue()` call. Capability = `permission_gate_op`.
2. Inside `surge_invoke(capability, params)` — right before the Broker HTTP call. Capability = `broker_capability`.

```python
from sol_shadow import shadow_emit_sync

# call_tool:
shadow_emit_sync(
    capability="permission_gate_op",
    args={"tool": tool_name, "args": args},
    intent=f"brain.call_tool {tool_name}",
)

# surge_invoke:
shadow_emit_sync(
    capability="broker_capability",
    args={"capability": capability, "params": params},
    intent=f"brain.surge_invoke {capability}",
)
```

## Surge Runner integration (`/opt/surgexi/brain/surge_curator.py`)

Inside `_dispatch_surge_handles()`, right before the POST to `:9100/tasks`:

```python
from sol_shadow import shadow_emit_sync

shadow_emit_sync(
    capability="surge_runner_task",
    args={"repo": repo, "issue": issue_num, "prompt": prompt_preview[:200]},
    intent=f"surge_curator dispatch {repo}#{issue_num}",
)
```

## Broker integration

Broker is a separate Docker container under `clawdbot` compose stack. Hook is installed at the *caller* side (Brain `surge_invoke()`), not inside Broker itself — Broker is the executor, Brain is the dispatcher. So the Broker-side shadow hook is fully covered by the Brain `surge_invoke` install above. No Broker code change is required for shadow.

## Environment variables to set in each agent's EnvironmentFile

```
SOL_URL=http://127.0.0.1:9320
SOL_SHADOW_ENABLED=true
SOL_AGENT_NAME=brain     # or surge_curator, etc.
SOL_AGENT_TIER=2
SOL_SHADOW_TIMEOUT_MS=50
SOL_SERVICE_TOKEN=...    # issued by SOL bootstrap (Week 2)
```

## Rollback

`SOL_SHADOW_ENABLED=false` and restart the agent — hook becomes a no-op.
