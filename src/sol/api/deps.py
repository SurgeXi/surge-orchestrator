"""FastAPI dependencies for auth, tenant context, DB session.

Three auth paths, in priority order:
  1. mTLS (headers X-Client-Cert-Verified + X-Client-CN from nginx terminator)
  2. Service token (X-SOL-Service-Token header)
  3. Admin JWT (Authorization: Bearer ...)

mTLS callers behave like services for downstream auth (allowed_tenants + claims),
but the audit log records auth_method=mtls instead of jwt-service.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request, status

from ..auth.jwt import AdminJwtAuth, AdminPrincipal
from ..auth.mtls import extract_mtls_principal
from ..auth.service_tokens import ServicePrincipal, ServiceTokenAuth


@dataclass
class CallerContext:
    principal_kind: str  # "service" | "admin" | "mtls"
    principal_id: str
    tenant_id: str
    allowed_tenants: list[str]
    sol_role: str | None = None
    shadow_mode: bool = False
    claims: list[str] = field(default_factory=list)
    auth_method: str = "unknown"  # mtls | jwt-service | jwt-admin
    jti: str | None = None  # JWT id when applicable (for audit + revoke)


def get_caller(
    request: Request,
    authorization: str | None = Header(default=None),
    x_sol_service_token: str | None = Header(default=None, alias="X-SOL-Service-Token"),
    x_surgexi_tenant: str | None = Header(default=None, alias="X-SurgeXi-Tenant"),
    x_sol_mode: str | None = Header(default=None, alias="X-SOL-Mode"),
) -> CallerContext:
    shadow = (x_sol_mode or "").strip().lower() == "shadow"

    # ---- 1. mTLS path (nginx headers) ----
    mtls_p = extract_mtls_principal(request)
    if mtls_p is not None:
        tenant = x_surgexi_tenant or (
            mtls_p.allowed_tenants[0] if mtls_p.allowed_tenants else "platform"
        )
        if (
            tenant != "platform"
            and tenant not in mtls_p.allowed_tenants
            and "*" not in mtls_p.allowed_tenants
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"mTLS caller not allowed for tenant {tenant}",
            )
        return CallerContext(
            principal_kind="mtls",
            principal_id=mtls_p.caller_name,
            tenant_id=tenant,
            allowed_tenants=mtls_p.allowed_tenants,
            shadow_mode=shadow,
            claims=mtls_p.claims,
            auth_method="mtls",
        )

    # ---- 2. Service-token path ----
    if x_sol_service_token:
        principal: ServicePrincipal = ServiceTokenAuth.verify(x_sol_service_token)
        tenant = x_surgexi_tenant or (
            principal.allowed_tenants[0] if principal.allowed_tenants else "platform"
        )
        if (
            tenant != "platform"
            and tenant not in principal.allowed_tenants
            and "*" not in principal.allowed_tenants
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"service token not allowed for tenant {tenant}",
            )
        return CallerContext(
            principal_kind="service",
            principal_id=principal.service_name,
            tenant_id=tenant,
            allowed_tenants=principal.allowed_tenants,
            shadow_mode=shadow,
            claims=principal.claims,
            auth_method="jwt-service",
            jti=principal.jti,
        )

    # ---- 3. Admin-JWT path ----
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        admin: AdminPrincipal = AdminJwtAuth.verify(token)
        return CallerContext(
            principal_kind="admin",
            principal_id=admin.username,
            tenant_id=x_surgexi_tenant or "platform",
            allowed_tenants=admin.allowed_tenants or ["*"],
            sol_role=admin.sol_role,
            shadow_mode=shadow,
            auth_method="jwt-admin",
            jti=admin.jti,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing mTLS cert, service token, or JWT",
    )


def require_admin(caller: CallerContext = Depends(get_caller)) -> CallerContext:
    if caller.principal_kind != "admin" or caller.sol_role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return caller


def require_approver(caller: CallerContext = Depends(get_caller)) -> CallerContext:
    if caller.principal_kind != "admin" or caller.sol_role not in ("admin", "approver"):
        raise HTTPException(status_code=403, detail="approver role required")
    return caller
