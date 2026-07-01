# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Email delivery rendering + safety net tests.

Doesn't touch a real SMTP server. Verifies:
  - disabled SMTP returns an unsuccessful attempt with a clear response
  - URL builder embeds a verifiable signed callback token
  - HTML + text alternative both render the approval metadata
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sol.auth import callback_tokens
from sol.delivery import email as email_mod


@pytest.fixture(autouse=True)
def _smtp_disabled(monkeypatch):
    """Force SMTP_ENABLED=false for unit tests."""
    monkeypatch.setenv("SOL_SMTP_ENABLED", "false")
    monkeypatch.setenv("SOL_CALLBACK_BASE_URL", "https://sol.test.local")
    from sol import settings as _s
    _s.get_settings.cache_clear()
    callback_tokens.reset_secret_cache()
    yield
    _s.get_settings.cache_clear()
    callback_tokens.reset_secret_cache()


def _sample_approval() -> dict:
    return {
        "id": uuid.uuid4(),
        "tenant_id": "timesavedap",
        "actor_id": "brain",
        "capability": "permission_gate_op",
        "args_json": {
            "target": "write_file",
            "tool": "write_file",
            "path": "/tmp/test.txt",
            "risk": "mutate",
        },
        "intent": "test_intent",
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }


def test_disabled_smtp_returns_disabled_response():
    approval = _sample_approval()
    delivery = email_mod.EmailDelivery()
    result = asyncio.run(delivery.deliver(approval, "operator@example.com"))
    assert result.channel == "email"
    assert result.succeeded is False
    assert result.response == "smtp_disabled"


def test_invalid_target_short_circuits(monkeypatch):
    monkeypatch.setenv("SOL_SMTP_ENABLED", "true")
    from sol import settings as _s
    _s.get_settings.cache_clear()
    try:
        approval = _sample_approval()
        result = asyncio.run(email_mod.EmailDelivery().deliver(approval, "not-an-email"))
        assert result.succeeded is False
        assert result.response == "invalid_email_target"
    finally:
        _s.get_settings.cache_clear()


def test_url_builder_embeds_verifiable_token():
    approval_id = uuid.uuid4()
    url = email_mod._build_decide_url(approval_id, "approve", "https://sol.test.local")
    assert url.startswith("https://sol.test.local/v1/sol/approvals/")
    assert str(approval_id) in url
    assert "decision=approve" in url
    # Pull the token out and verify
    token_part = url.split("token=", 1)[1].split("&", 1)[0]
    # URL-decode percent-encoded dots etc.
    from urllib.parse import unquote
    claims = callback_tokens.verify(unquote(token_part))
    assert claims.approval_id == approval_id
    assert claims.decision == "approve"


def test_render_includes_capability_and_links():
    approval = _sample_approval()
    approve_url = "https://sol.test.local/approve"
    deny_url = "https://sol.test.local/deny"
    subject, text, html = email_mod._render(approval, approve_url, deny_url)
    assert "permission_gate_op" in subject
    assert "timesavedap" in subject
    assert approve_url in text and deny_url in text
    assert approve_url in html and deny_url in html
    assert "permission_gate_op" in html
    assert "Approve" in html and "Deny" in html


def test_summarize_args_picks_known_keys():
    s = email_mod._summarize_args({"path": "/tmp/a", "cmd": "rm -rf /", "extra": "noise"})
    assert "path=/tmp/a" in s
    assert "cmd=rm -rf /" in s
    # extra is dropped
    assert "noise" not in s
