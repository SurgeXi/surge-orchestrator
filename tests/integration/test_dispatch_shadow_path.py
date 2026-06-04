"""Integration test for the shadow-only dispatch path.

Skipped unless SOL_TEST_DATABASE_URL is set (a writable Postgres reachable
from CI or local). This guard keeps unit-test runs offline-safe.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("SOL_TEST_DATABASE_URL"),
    reason="needs a real Postgres via SOL_TEST_DATABASE_URL",
)


@pytest.fixture(autouse=True)
def _wire_test_db(monkeypatch):
    monkeypatch.setenv("SOL_DATABASE_URL", os.environ["SOL_TEST_DATABASE_URL"])
    monkeypatch.setenv("SOL_ENVIRONMENT", "dev")
    monkeypatch.setenv("SOL_ENFORCE", "false")
    monkeypatch.setenv("SOL_SHADOW_ENABLED", "true")
    from sol import settings as _s
    _s.get_settings.cache_clear()
    yield


def test_dispatch_writes_audit_row_in_shadow_mode():
    from sol.auth.service_tokens import ServiceTokenAuth
    from sol.main import create_app

    client = TestClient(create_app())
    token = ServiceTokenAuth.issue("integration-test", ["timesavedap"], ["dispatch"])

    trace_id = str(uuid.uuid4())
    body = {
        "capability": "broker_capability",
        "args": {"capability": "db_query", "params": {"q": "SELECT 1"}},
        "context": {
            "tenant_id": "timesavedap",
            "actor": {"kind": "agent", "id": "integration-test", "tier": 2},
            "identity": {"logged_in_user": None},
            "intent": "pytest shadow path",
            "trace_id": trace_id,
        },
        "options": {"block_until_seconds": 0},
    }
    r = client.post(
        "/v1/sol/dispatch",
        json=body,
        headers={
            "X-SOL-Service-Token": token,
            "X-SurgeXi-Tenant": "timesavedap",
            "X-SOL-Mode": "shadow",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "shadow"
    assert data["trace_id"] == trace_id
    assert uuid.UUID(data["audit_id"])
