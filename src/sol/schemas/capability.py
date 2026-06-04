"""Pydantic schemas for capability registration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CapabilityRegister(BaseModel):
    name: str
    owner_service: str
    min_tier: int = Field(ge=0, le=3)
    handler_kind: Literal["broker", "permission_gate", "surge_runner", "vertical_agent", "internal"]
    handler_endpoint: str
    args_schema_json: dict[str, Any]
    description: str | None = None
    rate_limit_json: dict[str, Any] | None = None
    requires_human: bool = False
    expiry_seconds: int | None = None


class CapabilityRead(BaseModel):
    name: str
    owner_service: str
    min_tier: int
    handler_kind: str
    handler_endpoint: str
    description: str | None
    requires_human: bool
    expiry_seconds: int | None
    status: str
    registered_at: datetime
    last_registered_at: datetime


class CapabilityListResponse(BaseModel):
    count: int
    items: list[CapabilityRead]
