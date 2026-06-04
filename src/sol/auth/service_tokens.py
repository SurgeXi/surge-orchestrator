"""Service-token issuance + verification (90-day EdDSA JWT per spec §4).

Same key model as admin JWT (auth/keystore.py — supports rotation).
Carries `jti` for revocation; verifier checks revoked_tokens.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException

from ..settings import get_settings
from .keystore import current_signing_key, verify_key_for
from .revocation import is_revoked


@dataclass
class ServicePrincipal:
    service_name: str
    allowed_tenants: list[str]
    claims: list[str] = field(default_factory=list)
    jti: str | None = None


class ServiceTokenAuth:
    @staticmethod
    def issue(
        service_name: str,
        allowed_tenants: list[str],
        claims: list[str] | None = None,
        jti: str | None = None,
    ) -> tuple[str, str]:
        """Return (token, jti). Caller persists jti to sol.issued_tokens."""
        s = get_settings()
        km = current_signing_key()
        now = datetime.now(UTC)
        jti = jti or str(uuid.uuid4())
        payload = {
            "sub": service_name,
            "service_name": service_name,
            "allowed_tenants": allowed_tenants,
            "claims": claims or [],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=s.jwt_service_ttl_days)).timestamp()),
            "iss": "sol",
            "kind": "service",
            "jti": jti,
        }
        token = jwt.encode(
            payload, km.private_pem, algorithm=km.algorithm, headers={"kid": km.kid}
        )
        return token, jti

    @staticmethod
    def verify(token: str) -> ServicePrincipal:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise HTTPException(401, detail=f"invalid service token header: {e}") from None
        kid = unverified_header.get("kid")
        # Try kid'd key first; fall through to every other (rotation cycles
        # the "current" name so kid alone doesn't pin a unique key).
        primary = verify_key_for(kid)
        seen_kids = {k.kid for k in primary}
        fallbacks = [k for k in verify_key_for(None) if k.kid not in seen_kids]
        candidates = primary + fallbacks
        last_err: Exception | None = None
        data = None
        for km in candidates:
            try:
                data = jwt.decode(
                    token, km.public_pem, algorithms=[km.algorithm], issuer="sol"
                )
                break
            except jwt.PyJWTError as e:
                last_err = e
                continue
        if data is None:
            raise HTTPException(401, detail=f"invalid service token: {last_err}") from None

        if data.get("kind") != "service":
            raise HTTPException(401, detail="not a service token")

        jti = data.get("jti")
        if jti and is_revoked(jti):
            raise HTTPException(401, detail="token revoked")

        return ServicePrincipal(
            service_name=data["service_name"],
            allowed_tenants=data.get("allowed_tenants", []),
            claims=data.get("claims", []),
            jti=jti,
        )
