# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Unit tests for the surge-runner executor (Phase 3.4)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from sol.executors import surge_runner as exec_mod


@pytest.fixture
def token_file(tmp_path: Path, monkeypatch) -> Path:
    p = tmp_path / "surge-runner.token"
    p.write_text("test-token-abc")
    monkeypatch.setenv("SOL_SURGE_RUNNER_TOKEN_PATH", str(p))
    return p


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_missing_token_returns_error(monkeypatch, tmp_path):
    missing = tmp_path / "missing.token"
    monkeypatch.setenv("SOL_SURGE_RUNNER_TOKEN_PATH", str(missing))
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", {"prompt": "x"}))
    assert res["status"] == "error"
    assert res["exit_code"] == 2
    assert "token missing" in res["summary"]


def test_missing_prompt_returns_error(token_file):
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", {}))
    assert res["status"] == "error"
    assert res["exit_code"] == 22
    assert "prompt" in res["stderr"]


def test_happy_path_forwards_and_returns_task_id(token_file, monkeypatch):
    captured = {}

    class _MockResp:
        status_code = 200
        text = '{"id": "task-42", "queued": true}'

        def json(self) -> dict:
            return {"id": "task-42", "queued": True}

    class _MockClient:
        def __init__(self, *a, **kw):
            self._timeout = kw.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _MockResp()

    monkeypatch.setattr(exec_mod.httpx, "AsyncClient", _MockClient)
    monkeypatch.setenv("SOL_SURGE_RUNNER_BASE_URL", "http://runner.test:9100")

    args = {
        "prompt": "implement issue #42",
        "system_prompt": "you are surge",
        "source": "sol-dispatch",
        "external_id": "issue-42",
        "metadata": {"repo": "SurgeXi/test-repo", "issue_number": 42},
        "max_steps": 30,
        "allowed_ssh_hosts": ["surgecore"],
        "junk_unknown_key": "should not be forwarded",
    }
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", args))

    assert res["status"] == "success"
    assert res["exit_code"] == 0
    assert "task-42" in res["summary"]
    assert captured["url"] == "http://runner.test:9100/tasks"
    assert captured["headers"]["Authorization"] == "Bearer test-token-abc"
    assert "junk_unknown_key" not in captured["json"], (
        "executor must filter unknown keys, not blindly pass through"
    )
    assert captured["json"]["metadata"]["repo"] == "SurgeXi/test-repo"
    assert captured["json"]["allowed_ssh_hosts"] == ["surgecore"]


def test_http_error_from_runner_returned(token_file, monkeypatch):
    class _MockResp:
        status_code = 503
        text = "runner is sad"

        def json(self):
            raise ValueError("not json")

    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _MockResp()

    monkeypatch.setattr(exec_mod.httpx, "AsyncClient", _MockClient)
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", {"prompt": "x"}))
    assert res["status"] == "error"
    assert res["exit_code"] == 503
    assert "HTTP 503" in res["summary"]


def test_timeout_classified(token_file, monkeypatch):
    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            raise httpx.TimeoutException("slow runner", request=None)

    monkeypatch.setattr(exec_mod.httpx, "AsyncClient", _MockClient)
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", {"prompt": "x"}))
    assert res["status"] == "error"
    assert res["exit_code"] == 124
    assert "timeout" in res["summary"]


def test_long_body_is_truncated(token_file, monkeypatch):
    big = "x" * (exec_mod._MAX_CAPTURE_BYTES + 1000)

    class _MockResp:
        status_code = 200
        text = big

        def json(self):
            return {}

    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _MockResp()

    monkeypatch.setattr(exec_mod.httpx, "AsyncClient", _MockClient)
    res = asyncio.run(exec_mod.execute_runner("surge_runner_dispatch", {"prompt": "x"}))
    assert res["status"] == "success"
    assert len(res["stdout"]) <= exec_mod._MAX_CAPTURE_BYTES
    assert "truncated" in res["stdout"]
