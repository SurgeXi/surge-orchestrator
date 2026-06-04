"""JWT issue + verify for human admins (60 min TTL per spec §10 #1)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from jose import JWTError, jwt

from ..settings import get_settings

_DEFAULT_DEV_SECRET = "dev-only-not-for-production-jwt-hmac-secret-32-chars-min!"


def _load_signing_material() -> tuple[str, str]:
    """Return (private_pem_or_hmac, algorithm)."""
    s = get_settings()
    key_path = s.jwt_signing_key_path
    if os.path.isfile(key_path):
        with open(key_path, "rb") as f:
            pem = f.read().decode("utf-8")
        return pem, "EdDSA"
    if s.environment == "production":
        raise RuntimeError(
            f"JWT signing key not found at {key_path} (production requires Ed25519 key)"
        )
    return _DEFAULT_DEV_SECRET, "HS256"


def _load_verify_material() -> tuple[str, str]:
    s = get_settings()
    pub = s.jwt_signing_pubkey_path
    if os.path.isfile(pub):
        with open(pub, "rb") as f:
            return f.read().decode("utf-8"), "EdDSA"
    if s.environment == "production":
        raise RuntimeError(f"JWT public key not found at {pub}")
    return _DEFAULT_DEV_SECRET, "HS256"


@dataclass
class AdminPrincipal:
    username: str
    sol_role: str
    allowed_tenants: list[str]


class AdminJwtAuth:
    """Verify-side JWT for human admins."""

    @staticmethod
    def issue(username: str, sol_role: str, allowed_tenants: list[str] | None = None) -> str:
        s = get_settings()
        key, alg = _load_signing_material()
        now = datetime.now(UTC)
        payload = {
            "sub": username,
            "sol_role": sol_role,
            "allowed_tenants": allowed_tenants or ["*"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=s.jwt_admin_ttl_minutes)).timestamp()),
            "iss": "sol",
        }
        return jwt.encode(payload, key, algorithm=alg)

    @staticmethod
    def verify(token: str) -> AdminPrincipal:
        key, alg = _load_verify_material()
        try:
            data = jwt.decode(token, key, algorithms=[alg], issuer="sol")
        except JWTError as e:
            raise HTTPException(401, detail=f"invalid admin JWT: {e}") from None
        return AdminPrincipal(
            username=data["sub"],
            sol_role=data.get("sol_role", "viewer"),
            allowed_tenants=data.get("allowed_tenants", ["*"]),
        )
