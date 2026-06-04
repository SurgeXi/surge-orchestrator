"""Unit tests for the SOL broker executor (Phase 3.3 Week 3)."""
from __future__ import annotations

import json
import sys
import types

from sol.executors import broker as broker_exec


def _install_fake_httpx(monkeypatch, *, status: int, body, raise_exc=None):
    """Inject a fake ``httpx`` module exporting ``post`` + ``HTTPError``."""
    captured: dict = {}

    class FakeResp:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            if isinstance(self._body, dict | list):
                return self._body
            raise json.JSONDecodeError("nope", str(self._body), 0)

    class FakeHTTPError(Exception):
        pass

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        if raise_exc:
            raise raise_exc
        return FakeResp(status, body)

    fake = types.ModuleType("httpx")
    fake.post = fake_post
    fake.HTTPError = FakeHTTPError
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return captured, FakeHTTPError


def test_executor_returns_error_when_token_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SOL_BROKER_API_TOKEN_PATH", str(tmp_path / "missing.token"))
    r = broker_exec.execute_broker("db_query", {"sql": "select 1"})
    assert r["outcome"] == "error"
    assert "token missing" in r["summary"]
    assert r["capability"] == "db_query"


def test_executor_forwards_to_broker_and_returns_dispatch_result(tmp_path, monkeypatch):
    tok = tmp_path / "broker.token"
    tok.write_text("sometoken")
    monkeypatch.setenv("SOL_BROKER_API_TOKEN_PATH", str(tok))
    monkeypatch.setenv("SOL_BROKER_URL", "http://broker.test:8220")

    body = {
        "outcome": "success",
        "summary": "1 row",
        "data": {"rows": [[1]]},
        "audit_id": "abc-123",
        "capability": "db_query",
    }
    captured, _ = _install_fake_httpx(monkeypatch, status=200, body=body)

    r = broker_exec.execute_broker(
        "db_query",
        {"sql": "select 1"},
        tenant_id="system",
        actor_id="brain",
        trace_id="trace-xyz",
    )

    assert r["outcome"] == "success"
    assert r["data"]["rows"] == [[1]]
    assert r["capability"] == "db_query"
    assert captured["url"] == "http://broker.test:8220/v1/surge/dispatch"
    assert captured["json"] == {
        "capability": "db_query",
        "params": {"sql": "select 1"},
        "tenant_id": "system",
    }
    assert captured["headers"]["X-SOL-Bypass"] == "true"
    assert captured["headers"]["Authorization"] == "Bearer sometoken"
    assert captured["headers"]["X-SOL-Trace-Id"] == "trace-xyz"
    assert captured["headers"]["X-SOL-Actor"] == "brain"


def test_executor_returns_error_on_http_failure(tmp_path, monkeypatch):
    tok = tmp_path / "broker.token"
    tok.write_text("sometoken")
    monkeypatch.setenv("SOL_BROKER_API_TOKEN_PATH", str(tok))
    monkeypatch.setenv("SOL_BROKER_URL", "http://broker.test:8220")

    body = {"detail": "invalid capability"}
    _install_fake_httpx(monkeypatch, status=400, body=body)
    r = broker_exec.execute_broker("bogus", {})
    assert r["outcome"] == "error"
    assert "broker HTTP 400" in r["summary"]


def test_executor_returns_error_on_transport_failure(tmp_path, monkeypatch):
    tok = tmp_path / "broker.token"
    tok.write_text("sometoken")
    monkeypatch.setenv("SOL_BROKER_API_TOKEN_PATH", str(tok))
    monkeypatch.setenv("SOL_BROKER_URL", "http://broker.test:8220")

    # We need the exception class to subclass the fake httpx.HTTPError, so
    # we install once then raise an instance of that captured class.

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

    class FakeHTTPError(Exception):
        pass

    def fake_post(*a, **kw):
        raise FakeHTTPError("connect refused")

    fake = types.ModuleType("httpx")
    fake.post = fake_post
    fake.HTTPError = FakeHTTPError
    monkeypatch.setitem(sys.modules, "httpx", fake)

    r = broker_exec.execute_broker("db_query", {})
    assert r["outcome"] == "error"
    assert "broker_unreachable" in r["summary"]
