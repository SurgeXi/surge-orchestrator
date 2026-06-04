"""JWT issue + verify for human admins (60 min TTL per spec §10 #1).

Key model: see auth/keystore.py — supports rotation (current + prev-1/prev-2).
Algorithm: EdDSA in production, HS256 in dev fallback only.

Token revocation: every JWT carries a `jti` claim; the verifier consults the
revoked_tokens table (with in-memory cache) and rejects revoked tokens.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException

from ..settings import get_settings
from .keystore import current_signing_key, verify_key_for
from .revocation import is_revoked


@dataclass
class AdminPrincipal:
    username: str
    sol_role: str
    allowed_tenants: list[str]
    jti: str | None = None


class AdminJwtAuth:
    """Issue + verify human-admin JWTs."""

    @staticmethod
    def issue(
        username: str,
        sol_role: str,
        allowed_tenants: list[str] | None = None,
        jti: str | None = None,
    ) -> tuple[str, str]:
        """Return (token, jti). Caller persists jti to sol.issued_tokens."""
        s = get_settings()
        km = current_signing_key()
        now = datetime.now(UTC)
        jti = jti or str(uuid.uuid4())
        payload = {
            "sub": username,
            "sol_role": sol_role,
            "allowed_tenants": allowed_tenants or ["*"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=s.jwt_admin_ttl_minutes)).timestamp()),
            "iss": "sol",
            "jti": jti,
            "kind": "admin",
        }
        token = jwt.encode(
            payload, km.private_pem, algorithm=km.algorithm, headers={"kid": km.kid}
        )
        return token, jti

    @staticmethod
    def verify(token: str) -> AdminPrincipal:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise HTTPException(401, detail=f"invalid admin JWT header: {e}") from None
        kid = unverified_header.get("kid")
        candidates = verify_key_for(kid)
        last_err: Exception | None = None
        for km in candidates:
            try:
                data = jwt.decode(
                    token, km.public_pem, algorithms=[km.algorithm], issuer="sol"
                )
                break
            except jwt.PyJWTError as e:
                last_err = e
                continue
        else:
            raise HTTPException(401, detail=f"invalid admin JWT: {last_err}") from None

        if data.get("kind") not in (None, "admin"):
            raise HTTPException(401, detail="wrong token kind for admin path")

        jti = data.get("jti")
        if jti and is_revoked(jti):
            raise HTTPException(401, detail="token revoked")

        return AdminPrincipal(
            username=data["sub"],
            sol_role=data.get("sol_role", "viewer"),
            allowed_tenants=data.get("allowed_tenants", ["*"]),
            jti=jti,
        )
