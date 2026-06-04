"""FastAPI dependencies for auth, tenant context, DB session."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from ..auth.jwt import AdminJwtAuth, AdminPrincipal
from ..auth.service_tokens import ServicePrincipal, ServiceTokenAuth


@dataclass
class CallerContext:
    principal_kind: str  # "service" | "admin"
    principal_id: str
    tenant_id: str
    allowed_tenants: list[str]
    sol_role: str | None = None
    shadow_mode: bool = False


def get_caller(
    request: Request,
    authorization: str | None = Header(default=None),
    x_sol_service_token: str | None = Header(default=None, alias="X-SOL-Service-Token"),
    x_surgexi_tenant: str | None = Header(default=None, alias="X-SurgeXi-Tenant"),
    x_sol_mode: str | None = Header(default=None, alias="X-SOL-Mode"),
) -> CallerContext:
    shadow = (x_sol_mode or "").strip().lower() == "shadow"

    if x_sol_service_token:
        principal: ServicePrincipal = ServiceTokenAuth.verify(x_sol_service_token)
        tenant = x_surgexi_tenant or (
            principal.allowed_tenants[0] if principal.allowed_tenants else "platform"
        )
        if tenant != "platform" and tenant not in principal.allowed_tenants and "*" not in principal.allowed_tenants:
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
        )

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
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing service token or JWT",
    )


def require_admin(caller: CallerContext = Depends(get_caller)) -> CallerContext:
    if caller.principal_kind != "admin" or caller.sol_role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return caller


def require_approver(caller: CallerContext = Depends(get_caller)) -> CallerContext:
    if caller.principal_kind != "admin" or caller.sol_role not in ("admin", "approver"):
        raise HTTPException(status_code=403, detail="approver role required")
    return caller
