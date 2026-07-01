# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""POST /v1/sol/capabilities/register and GET /v1/sol/capabilities."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Capability
from ..observability.logging import get_logger
from ..observability.metrics import capabilities_active
from ..schemas.capability import (
    CapabilityListResponse,
    CapabilityRead,
    CapabilityRegister,
)
from .deps import CallerContext, get_caller

router = APIRouter()
log = get_logger(__name__)


@router.post(
    "/capabilities/register",
    response_model=CapabilityRead,
    status_code=201,
)
def register_capability(
    payload: CapabilityRegister,
    caller: CallerContext = Depends(get_caller),
    db: Session = Depends(get_db),
) -> CapabilityRead:
    # auth gate: service tokens with register_capability claim, OR admin role.
    from fastapi import HTTPException

    if caller.principal_kind == "admin":
        if caller.sol_role != "admin":
            raise HTTPException(403, detail="admin role required")
    elif caller.principal_kind == "service":
        if "register_capability" not in (caller.claims or []):
            raise HTTPException(
                403, detail="service token missing register_capability claim"
            )
    else:
        raise HTTPException(403, detail="forbidden")

    now = datetime.now(UTC)
    stmt = insert(Capability).values(
        name=payload.name,
        owner_service=payload.owner_service,
        min_tier=payload.min_tier,
        handler_kind=payload.handler_kind,
        handler_endpoint=payload.handler_endpoint,
        args_schema_json=payload.args_schema_json,
        description=payload.description,
        rate_limit_json=payload.rate_limit_json,
        requires_human=payload.requires_human,
        expiry_seconds=payload.expiry_seconds,
        last_registered_at=now,
        status="active",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "owner_service": payload.owner_service,
            "min_tier": payload.min_tier,
            "handler_kind": payload.handler_kind,
            "handler_endpoint": payload.handler_endpoint,
            "args_schema_json": payload.args_schema_json,
            "description": payload.description,
            "rate_limit_json": payload.rate_limit_json,
            "requires_human": payload.requires_human,
            "expiry_seconds": payload.expiry_seconds,
            "last_registered_at": now,
            "status": "active",
        },
    )
    db.execute(stmt)
    db.commit()

    cap = db.get(Capability, payload.name)
    log.info(
        "sol.capability.registered",
        name=cap.name,
        owner_service=cap.owner_service,
        handler_kind=cap.handler_kind,
    )
    _refresh_capability_gauge(db)
    return _to_read(cap)


@router.get("/capabilities", response_model=CapabilityListResponse)
def list_capabilities(
    status: str | None = Query(default="active"),
    db: Session = Depends(get_db),
    caller: CallerContext = Depends(get_caller),
) -> CapabilityListResponse:
    q = db.query(Capability)
    if status:
        q = q.filter(Capability.status == status)
    items = q.order_by(Capability.name.asc()).all()
    return CapabilityListResponse(
        count=len(items),
        items=[_to_read(c) for c in items],
    )


def _to_read(c: Capability) -> CapabilityRead:
    return CapabilityRead(
        name=c.name,
        owner_service=c.owner_service,
        min_tier=c.min_tier,
        handler_kind=c.handler_kind,
        handler_endpoint=c.handler_endpoint,
        description=c.description,
        requires_human=c.requires_human,
        expiry_seconds=c.expiry_seconds,
        status=c.status,
        registered_at=c.registered_at,
        last_registered_at=c.last_registered_at,
    )


def _refresh_capability_gauge(db: Session) -> None:
    n = db.query(func.count(Capability.name)).filter(Capability.status == "active").scalar()
    capabilities_active.set(int(n or 0))
