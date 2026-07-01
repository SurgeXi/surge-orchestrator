# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Signed one-tap callback URLs for email/chat delivery channels.

Phase 3.2 (Week 2) — email and chat-bubble delivery embed a per-decision
short-lived signed URL so an approver can decide with a single click and
zero credentials. Distinct from AdminJwtAuth (60-min EdDSA admin login):
this signer is HMAC-SHA256 over a fixed URL-safe payload, with a short
TTL (default 15 min, capped by ``jwt_callback_ttl_minutes``).

Token layout (compact, URL-safe):

    <approval_id>.<decision>.<exp_unix>.<hmac_b64u>

- approval_id : UUID of the sol.approvals row
- decision    : "approve" | "deny"
- exp_unix    : integer unix-time when the token stops verifying
- hmac_b64u   : HMAC-SHA256(secret, "approval_id.decision.exp_unix"), b64url

A single-use guarantee is enforced at the API layer (the approvals row
moves out of ``pending`` after the first valid decide call). Replay is
bounded by exp + the row's status check.

Secret material:
    /etc/sol/keys/callback_hmac.key   (chmod 600, 32+ bytes)
If missing in dev, falls back to a process-stable secret so unit tests
don't need filesystem state.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from ..settings import get_settings

_DEV_FALLBACK_SECRET = b"dev-only-callback-hmac-secret-do-not-use-in-prod-32b!"
_ALLOWED_DECISIONS = {"approve", "deny"}


@dataclass(frozen=True)
class CallbackClaims:
    approval_id: uuid.UUID
    decision: str  # "approve" | "deny"
    exp_unix: int


@lru_cache(maxsize=1)
def _secret() -> bytes:
    s = get_settings()
    path = getattr(s, "callback_hmac_key_path", None) or "/etc/sol/keys/callback_hmac.key"
    try:
        raw = Path(path).read_bytes().strip()
        if len(raw) >= 16:
            return raw
    except OSError:
        pass
    # dev fallback — production deployments MUST provision the key file.
    return _DEV_FALLBACK_SECRET


def _b64u_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(message: str) -> str:
    mac = hmac.new(_secret(), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64u_encode(mac)


def issue(approval_id: uuid.UUID, decision: str, ttl_minutes: int | None = None) -> str:
    if decision not in _ALLOWED_DECISIONS:
        raise ValueError(f"decision must be one of {_ALLOWED_DECISIONS}")
    s = get_settings()
    ttl = int(ttl_minutes if ttl_minutes is not None else (s.jwt_callback_ttl_minutes or 15))
    exp = int(time.time()) + ttl * 60
    body = f"{approval_id}.{decision}.{exp}"
    sig = _sign(body)
    return f"{body}.{sig}"


def verify(token: str) -> CallbackClaims:
    """Return CallbackClaims on success. Raise HTTPException(401) otherwise."""
    if not token or token.count(".") != 3:
        raise HTTPException(status_code=401, detail="invalid_callback_token")
    body_id, body_dec, body_exp, body_sig = token.split(".", 3)
    body = f"{body_id}.{body_dec}.{body_exp}"
    expected = _sign(body)
    if not hmac.compare_digest(expected, body_sig):
        raise HTTPException(status_code=401, detail="invalid_callback_token")
    try:
        exp_unix = int(body_exp)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_callback_token") from None
    if exp_unix < int(time.time()):
        raise HTTPException(status_code=401, detail="callback_token_expired")
    if body_dec not in _ALLOWED_DECISIONS:
        raise HTTPException(status_code=401, detail="invalid_callback_token")
    try:
        approval_id = uuid.UUID(body_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_callback_token") from None
    return CallbackClaims(approval_id=approval_id, decision=body_dec, exp_unix=exp_unix)


def reset_secret_cache() -> None:
    """Test hook — clears the cached secret material."""
    _secret.cache_clear()
