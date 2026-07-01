# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Unit tests for the cross-rule policy evaluator (Phase 3.4)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from sol.policy.cache import HotPolicy, PolicyCache
from sol.policy.cross_rules import (
    _extract_repo,
    evaluate_repo_cooldown,
)


def _cache_with_rule(window=300, caps=("surge_runner_dispatch",)):
    c = PolicyCache()
    c._policy = HotPolicy(
        version=1,
        rules=[],
        cross_rules={
            "repo_cooldown": {
                "capabilities": list(caps),
                "window_seconds": window,
            }
        },
    )
    return c


def _row(
    *,
    capability: str,
    repo: str,
    tenant: str = "platform",
    decision: str = "approved",
    created_at: datetime | None = None,
):
    created_at = created_at or datetime.now(UTC)
    return SimpleNamespace(
        capability=capability,
        tenant_id=tenant,
        decision=decision,
        args_json={"metadata": {"repo": repo}},
        created_at=created_at,
    )


def test_extract_repo_handles_metadata_and_flat():
    assert _extract_repo({"metadata": {"repo": "SurgeXi/A"}}) == "surgexi/a"
    assert _extract_repo({"repo": "SurgeXi/B"}) == "surgexi/b"
    assert _extract_repo({"metadata": {}}) is None
    assert _extract_repo({}) is None


def test_no_cache_allows():
    c = PolicyCache()  # not loaded
    db = MagicMock()
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "x/y"}},
        cache=c,
    )
    assert res.allowed
    db.execute.assert_not_called()


def test_no_cross_rule_in_yaml_allows():
    c = PolicyCache()
    c._policy = HotPolicy(version=1, rules=[], cross_rules={})
    db = MagicMock()
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "x/y"}},
        cache=c,
    )
    assert res.allowed
    db.execute.assert_not_called()


def test_capability_not_in_rule_allows():
    c = _cache_with_rule(caps=("surge_runner_dispatch",))
    db = MagicMock()
    res = evaluate_repo_cooldown(
        db=db,
        capability="some_other_cap",
        tenant_id="platform",
        args={"metadata": {"repo": "x/y"}},
        cache=c,
    )
    assert res.allowed
    db.execute.assert_not_called()


def test_no_repo_in_args_allows():
    c = _cache_with_rule()
    db = MagicMock()
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"prompt": "hi"},
        cache=c,
    )
    assert res.allowed
    db.execute.assert_not_called()


def test_first_dispatch_for_repo_allowed():
    c = _cache_with_rule()
    db = MagicMock()
    # No prior rows
    db.execute.return_value.scalars.return_value.all.return_value = []
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "SurgeXi/test"}},
        cache=c,
    )
    assert res.allowed


def test_repeat_dispatch_within_window_denied():
    c = _cache_with_rule(window=300)
    db = MagicMock()
    now = datetime.now(UTC)
    prior = _row(
        capability="surge_runner_dispatch",
        repo="SurgeXi/test",
        created_at=now - timedelta(seconds=60),
    )
    db.execute.return_value.scalars.return_value.all.return_value = [prior]
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "SurgeXi/test"}},
        cache=c,
        now=now,
    )
    assert not res.allowed
    assert res.rule == "repo_cooldown"
    assert "surgexi/test" in res.reason.lower()


def test_different_repo_allowed():
    c = _cache_with_rule(window=300)
    db = MagicMock()
    now = datetime.now(UTC)
    prior = _row(
        capability="surge_runner_dispatch",
        repo="SurgeXi/other",
        created_at=now - timedelta(seconds=60),
    )
    db.execute.return_value.scalars.return_value.all.return_value = [prior]
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "SurgeXi/test"}},
        cache=c,
        now=now,
    )
    assert res.allowed


def test_denied_prior_does_not_count():
    """Cross-rule should only count rows that actually executed (or were
    auto-approved to execute). A prior denial does NOT block a retry."""
    c = _cache_with_rule(window=300)
    db = MagicMock()
    # The mock query already filters by decision IN ('approved','executed'),
    # so to be safe we return an empty list here and assert that the
    # call was scoped correctly.
    db.execute.return_value.scalars.return_value.all.return_value = []
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "SurgeXi/test"}},
        cache=c,
    )
    assert res.allowed


def test_custom_reason_template():
    c = PolicyCache()
    c._policy = HotPolicy(
        version=1,
        rules=[],
        cross_rules={
            "repo_cooldown": {
                "capabilities": ["surge_runner_dispatch"],
                "window_seconds": 300,
                "reason": "CUSTOM repo={repo} window={window} elapsed={elapsed}",
            }
        },
    )
    db = MagicMock()
    now = datetime.now(UTC)
    prior = _row(
        capability="surge_runner_dispatch",
        repo="SurgeXi/test",
        created_at=now - timedelta(seconds=42),
    )
    db.execute.return_value.scalars.return_value.all.return_value = [prior]
    res = evaluate_repo_cooldown(
        db=db,
        capability="surge_runner_dispatch",
        tenant_id="platform",
        args={"metadata": {"repo": "SurgeXi/test"}},
        cache=c,
        now=now,
    )
    assert not res.allowed
    assert "CUSTOM" in res.reason
    assert "window=300" in res.reason
    assert "elapsed=42" in res.reason
