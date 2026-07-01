# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Pydantic schemas for policy upsert."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class PolicyRule(BaseModel):
    rule_id: str
    description: str | None = None
    rule_kind: Literal["rate_limit", "anti_thrash", "tenant_isolation", "capability_tier"]
    match_json: dict[str, Any]
    window_seconds: int | None = None
    scope_field: str | None = None
    decision: Literal["deny", "deny-with-reason", "allow", "escalate"]
    decision_reason: str | None = None


class PolicyUpsertRequest(BaseModel):
    version: int
    created_by: str
    rules: list[PolicyRule]


class PolicyUpsertResponse(BaseModel):
    version: int
    rules_loaded: int
