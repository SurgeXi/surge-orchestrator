"""Service-token issuance + verification (90-day Ed25519 JWT per spec §4)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from jose import JWTError, jwt

from ..settings import get_settings

_DEFAULT_DEV_SECRET = "dev-only-service-token-hmac-secret-32-characters-minimum!"


def _signing() -> tuple[str, str]:
    s = get_settings()
    if os.path.isfile(s.jwt_signing_key_path):
        return open(s.jwt_signing_key_path).read(), "EdDSA"
    if s.environment == "production":
        raise RuntimeError("service-token signing key missing")
    return _DEFAULT_DEV_SECRET, "HS256"


def _verifying() -> tuple[str, str]:
    s = get_settings()
    if os.path.isfile(s.jwt_signing_pubkey_path):
        return open(s.jwt_signing_pubkey_path).read(), "EdDSA"
    if s.environment == "production":
        raise RuntimeError("service-token public key missing")
    return _DEFAULT_DEV_SECRET, "HS256"


@dataclass
class ServicePrincipal:
    service_name: str
    allowed_tenants: list[str]
    claims: list[str] = field(default_factory=list)


class ServiceTokenAuth:
    @staticmethod
    def issue(
        service_name: str,
        allowed_tenants: list[str],
        claims: list[str] | None = None,
    ) -> str:
        s = get_settings()
        key, alg = _signing()
        now = datetime.now(UTC)
        payload = {
            "sub": service_name,
            "service_name": service_name,
            "allowed_tenants": allowed_tenants,
            "claims": claims or [],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=s.jwt_service_ttl_days)).timestamp()),
            "iss": "sol",
            "kind": "service",
        }
        return jwt.encode(payload, key, algorithm=alg)

    @staticmethod
    def verify(token: str) -> ServicePrincipal:
        key, alg = _verifying()
        try:
            data = jwt.decode(token, key, algorithms=[alg], issuer="sol")
        except JWTError as e:
            raise HTTPException(401, detail=f"invalid service token: {e}") from None
        if data.get("kind") != "service":
            raise HTTPException(401, detail="not a service token")
        return ServicePrincipal(
            service_name=data["service_name"],
            allowed_tenants=data.get("allowed_tenants", []),
            claims=data.get("claims", []),
        )
