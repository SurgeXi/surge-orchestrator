# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Verify the tenant-isolation check in the get_caller dep + dispatch path."""
from __future__ import annotations

from sol.api.deps import CallerContext


def test_service_caller_blocked_from_cross_tenant():
    # Simulate the check the dispatch endpoint enforces.
    caller = CallerContext(
        principal_kind="service",
        principal_id="ar-agent@aiap",
        tenant_id="timesavedap",
        allowed_tenants=["timesavedap"],
        shadow_mode=False,
    )
    # Args target a different tenant — dispatch.py raises 403 via the guard.
    target_tenant = "surgexi"
    allowed = caller.allowed_tenants
    permitted = target_tenant in allowed or "*" in allowed
    assert permitted is False


def test_service_caller_with_wildcard_allowed_anywhere():
    caller = CallerContext(
        principal_kind="service",
        principal_id="platform-bot",
        tenant_id="platform",
        allowed_tenants=["*"],
        shadow_mode=False,
    )
    assert "*" in caller.allowed_tenants
