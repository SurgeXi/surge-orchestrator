"""Integration test for the enforce-path approval + email-callback decide.

Skipped unless SOL_TEST_DATABASE_URL is set. Does NOT send a real email;
SMTP_ENABLED=false so EmailDelivery returns 'smtp_disabled' and the
log_only channel takes over. The point is to verify:

  - X-SOL-Mode: enforce on a requires_human capability → approval row
    created + dispatches row updated with approval_id + decision=queued.
  - Calling GET /v1/sol/approvals/{id}/decide with a signed callback
    token transitions the row to approved (or denied) and is idempotent.
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
    monkeypatch.setenv("SOL_SMTP_ENABLED", "false")
    monkeypatch.setenv("SOL_CALLBACK_BASE_URL", "https://sol.test.local")
    from sol import settings as _s
    from sol.auth import callback_tokens
    _s.get_settings.cache_clear()
    callback_tokens.reset_secret_cache()
    yield


def _service_token() -> str:
    from sol.auth.service_tokens import ServiceTokenAuth
    token, _jti = ServiceTokenAuth.issue("integration-test", ["timesavedap"], ["dispatch"])
    return token


def test_enforce_creates_approval_and_callback_decide_finalizes():
    from sol.auth import callback_tokens
    from sol.main import create_app

    client = TestClient(create_app())
    token = _service_token()
    trace_id = str(uuid.uuid4())

    body = {
        "capability": "permission_gate_op",
        "args": {
            "tool": "write_file",
            "args": {"path": "/tmp/intg-test.txt", "content": "hi"},
            "risk": "mutate",
        },
        "context": {
            "tenant_id": "timesavedap",
            "actor": {"kind": "agent", "id": "brain", "tier": 2},
            "identity": {"logged_in_user": "todd"},
            "intent": "integration_test_enforce",
            "trace_id": trace_id,
        },
        # block_until=0 — don't wait; we approve out-of-band then re-query.
        "options": {"block_until_seconds": 0},
    }
    r = client.post(
        "/v1/sol/dispatch",
        json=body,
        headers={
            "X-SOL-Service-Token": token,
            "X-SurgeXi-Tenant": "timesavedap",
            "X-SOL-Mode": "enforce",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "queued"
    assert data["approval_id"]
    approval_id = uuid.UUID(data["approval_id"])

    # Approver clicks the email link — simulate with a freshly-minted token.
    cb_token = callback_tokens.issue(approval_id, "approve")
    r2 = client.get(
        f"/v1/sol/approvals/{approval_id}/decide",
        params={"token": cb_token, "decision": "approve"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "approved"

    # Idempotent re-click returns the existing state, not 409.
    r3 = client.get(
        f"/v1/sol/approvals/{approval_id}/decide",
        params={"token": cb_token, "decision": "approve"},
    )
    assert r3.status_code == 200
    assert r3.json().get("note") == "already_decided"


def test_callback_token_decision_mismatch_rejected():
    """An approve token MUST NOT be usable to issue a deny."""
    from sol.auth import callback_tokens
    from sol.main import create_app

    client = TestClient(create_app())
    token = _service_token()

    # Create an approval row by dispatching once.
    body = {
        "capability": "permission_gate_op",
        "args": {"tool": "run_bash", "args": {"cmd": "ls"}, "risk": "remote"},
        "context": {
            "tenant_id": "timesavedap",
            "actor": {"kind": "agent", "id": "brain", "tier": 2},
            "identity": {},
            "trace_id": str(uuid.uuid4()),
        },
        "options": {"block_until_seconds": 0},
    }
    r = client.post(
        "/v1/sol/dispatch",
        json=body,
        headers={
            "X-SOL-Service-Token": token,
            "X-SurgeXi-Tenant": "timesavedap",
            "X-SOL-Mode": "enforce",
        },
    )
    assert r.status_code == 200
    approval_id = uuid.UUID(r.json()["approval_id"])

    # Take an APPROVE token and try to use it on the DENY query — must 401.
    cb_token = callback_tokens.issue(approval_id, "approve")
    r2 = client.get(
        f"/v1/sol/approvals/{approval_id}/decide",
        params={"token": cb_token, "decision": "deny"},
    )
    assert r2.status_code == 401
