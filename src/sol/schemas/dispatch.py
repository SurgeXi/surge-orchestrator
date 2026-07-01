# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
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
    # Phase 3.3 Week 3: free-form payload from a downstream executor
    # (e.g. Broker's DispatchResult.data + audit_id + approval_id).
    # Optional so existing executors that don't produce structured data
    # (file ops, ssh) keep returning the lean shape.
    data: dict[str, Any] | None = None
    # Broker's own audit row id when SOL forwarded to broker — useful
    # for cross-referencing legacy audit during the migration window.
    broker_audit_id: str | None = None
    capability: str | None = None


class DispatchResponse(BaseModel):
    decision: Literal["approved", "denied", "queued", "escalated", "deferred", "executed", "shadow"]
    audit_id: uuid.UUID
    trace_id: str
    result: DispatchResult | None = None
    approval_id: uuid.UUID | None = None
    decision_path: str
    decision_reason: str | None = None
