"""Pydantic request/response models for dispatch."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class Actor(BaseModel):
    kind: Literal["agent", "human"]
    id: str
    tier: int


class Identity(BaseModel):
    logged_in_user: str | None = None
    session_surface: str | None = None
    geopro_target: str | None = None


class DispatchContext(BaseModel):
    tenant_id: str
    actor: Actor
    identity: Identity = Field(default_factory=Identity)
    intent: str | None = None
    trace_id: str
    parent_trace_id: str | None = None


class DispatchOptions(BaseModel):
    block_until_seconds: int = 30


class DispatchRequest(BaseModel):
    capability: str
    args: dict[str, Any]
    context: DispatchContext
    options: DispatchOptions = Field(default_factory=DispatchOptions)


class DispatchResult(BaseModel):
    status: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    summary: str | None = None


class DispatchResponse(BaseModel):
    decision: Literal["approved", "denied", "queued", "escalated", "deferred", "executed", "shadow"]
    audit_id: uuid.UUID
    trace_id: str
    result: DispatchResult | None = None
    approval_id: uuid.UUID | None = None
    decision_path: str
    decision_reason: str | None = None
