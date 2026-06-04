"""mTLS auth — trusts headers set by upstream nginx mTLS terminator.

Architecture (Phase 3.2):
  client (cert) -> nginx (mTLS verify, port 9321) -> SOL (HTTP, 127.0.0.1:9320)

nginx sets two headers when client presents a valid cert chain:
  X-Client-Cert-Verified: SUCCESS | NONE | FAILED:<reason>
  X-Client-CN:            <subject CN from client cert>

SOL trusts these headers ONLY when the request arrives via the loopback path
(127.0.0.1). Any external request bearing these headers without nginx in front
must be rejected to prevent spoof — enforced by binding SOL to 127.0.0.1
(see settings.host) and by an explicit check in the dependency.

CN encoding contract:
  <caller-name>.sol-client          e.g. "brain.sol-client"
The caller-name maps to a ServicePrincipal via the registered_callers table
(in /etc/sol/mtls-callers.yaml — same shape as service tokens) so SOL knows
the allowed_tenants + claims for that caller.

This module does NOT verify certs itself — that's nginx's job. It only
extracts the identity from the trusted headers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import HTTPException, Request

from ..settings import get_settings


@dataclass
class MtlsPrincipal:
    """Identity extracted from a verified client cert."""

    client_cn: str  # e.g. "brain.sol-client"
    caller_name: str  # e.g. "brain"
    allowed_tenants: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_callers() -> dict[str, dict]:
    """Load the mTLS callers registry from /etc/sol/mtls-callers.yaml.

    Shape:
      callers:
        brain:
          allowed_tenants: ["*"]
          claims: [dispatch, register_capability]
        broker:
          allowed_tenants: ["*"]
          claims: [dispatch]
        surge-runner:
          allowed_tenants: ["*"]
          claims: [dispatch]
        sol-admin:
          allowed_tenants: ["*"]
          claims: [admin, approver, register_capability]
    """
    s = get_settings()
    path = Path(s.mtls_callers_yaml_path)
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("callers", {}) or {}


def reload_callers() -> None:
    """Drop the cached callers registry — used by tests + admin reload."""
    _load_callers.cache_clear()


def _parse_caller_from_cn(cn: str) -> str:
    """Extract caller-name from CN '<caller>.sol-client'."""
    if not cn.endswith(".sol-client"):
        raise HTTPException(401, detail=f"mTLS CN missing .sol-client suffix: {cn!r}")
    return cn[: -len(".sol-client")]


def extract_mtls_principal(request: Request) -> MtlsPrincipal | None:
    """Return MtlsPrincipal if request carries valid mTLS headers, else None.

    Returns None — not exception — when no mTLS headers are present so the
    caller dependency can fall through to JWT / service-token paths.

    Raises 401 if headers are present but malformed (verify failed, missing CN,
    or CN not in the callers registry — fail closed).
    """
    verified = request.headers.get("X-Client-Cert-Verified")
    cn = request.headers.get("X-Client-CN")

    if verified is None and cn is None:
        return None  # no mTLS — caller will try other auth paths

    s = get_settings()
    # Trust headers only when the request hit us via loopback (nginx → SOL).
    # External traffic bypassing nginx must be rejected.
    if s.mtls_require_loopback:
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(
                401,
                detail=f"mTLS headers from non-loopback peer {client_host!r} rejected",
            )

    if (verified or "").upper() != "SUCCESS":
        raise HTTPException(401, detail=f"mTLS verify failed: {verified!r}")

    if not cn:
        raise HTTPException(401, detail="mTLS verify=SUCCESS but X-Client-CN missing")

    caller_name = _parse_caller_from_cn(cn)
    callers = _load_callers()
    record = callers.get(caller_name)
    if record is None:
        raise HTTPException(
            403,
            detail=f"mTLS caller {caller_name!r} not in registry",
        )

    return MtlsPrincipal(
        client_cn=cn,
        caller_name=caller_name,
        allowed_tenants=list(record.get("allowed_tenants", [])),
        claims=list(record.get("claims", [])),
    )


# ---------------------------------------------------------------------------
# Helper for ops: write a default mtls-callers.yaml when bootstrapping.
# Not used at runtime; called by scripts/issue_client_cert.sh.
# ---------------------------------------------------------------------------
DEFAULT_CALLERS_YAML = """\
# /etc/sol/mtls-callers.yaml
# Registry of mTLS callers. Each caller_name corresponds to a client cert
# with CN '<caller_name>.sol-client'. Managed by ops; SOL reads on startup
# and on admin-triggered reload.
callers:
  brain:
    allowed_tenants: ["*"]
    claims: [dispatch, register_capability]
  broker:
    allowed_tenants: ["*"]
    claims: [dispatch]
  surge-runner:
    allowed_tenants: ["*"]
    claims: [dispatch]
  sol-admin:
    allowed_tenants: ["*"]
    claims: [admin, approver, register_capability]
"""


def ensure_default_callers_file(path: str | os.PathLike) -> bool:
    """Create the callers file with defaults if it doesn't exist. Idempotent."""
    p = Path(path)
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CALLERS_YAML)
    p.chmod(0o640)
    return True
