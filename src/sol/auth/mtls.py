"""mTLS auth — trusts headers set by upstream nginx mTLS terminator.

Architecture (Phase 3.2):
  client (cert) -> nginx (mTLS verify, port 9321) -> SOL (HTTP, 127.0.0.1:9320)

nginx sets these headers when client presents a valid cert chain:
  X-Client-Cert-Verified: SUCCESS | NONE | FAILED:<reason>
  X-Client-CN:            <subject CN from client cert>
  X-SOL-Nginx-Token:      <shared secret proving nginx is the origin>

SOL trusts the cert-verified headers ONLY when X-SOL-Nginx-Token matches the
shared secret on disk at settings.nginx_shared_secret_path. This stops a
direct caller from spoofing the cert-verified headers by hitting SOL's HTTP
port directly (which also binds 127.0.0.1, but could be reached via
SSH-forwarded sockets, sidecar containers, etc).

Loopback IP check is a secondary defense layer (settings.mtls_require_loopback),
but the shared-secret token is the primary trust boundary because uvicorn's
proxy_headers middleware rewrites the apparent peer IP from X-Forwarded-For.

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
def _load_nginx_shared_secret() -> str | None:
    """Load the shared secret nginx must echo to prove origin.

    Returns None if file is missing — in that case the secret check is
    skipped (legacy behavior, falls back to loopback IP check only).

    File at settings.nginx_shared_secret_path; must be mode 640 root:todds.
    """
    s = get_settings()
    p = Path(s.nginx_shared_secret_path)
    if not p.is_file():
        return None
    try:
        secret = p.read_text().strip()
        return secret if secret else None
    except (PermissionError, OSError):
        return None


def reload_nginx_secret() -> None:
    _load_nginx_shared_secret.cache_clear()


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
    _load_nginx_shared_secret.cache_clear()


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

    # Primary trust boundary: nginx shared secret proves the request was
    # actually terminated by our mTLS nginx, not a direct caller spoofing
    # the cert headers via a sidecar HTTP socket on the same machine.
    expected = _load_nginx_shared_secret()
    if expected is not None:
        seen = request.headers.get("X-SOL-Nginx-Token")
        if seen != expected:
            raise HTTPException(
                401,
                detail="mTLS headers present but nginx-token mismatch",
            )

    # Secondary defense: loopback IP check (off by default since uvicorn's
    # proxy_headers middleware rewrites peer IP from X-Forwarded-For).
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
