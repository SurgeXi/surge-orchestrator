"""PolicyCache must load cross_rules from /etc/sol/policy.yaml (Phase 3.4)."""
from __future__ import annotations

from pathlib import Path

from sol.policy.cache import PolicyCache


def test_loads_cross_rules_block(tmp_path: Path):
    p = tmp_path / "policy.yaml"
    p.write_text(
        """
version: 7
expiry_defaults:
  standard: 86400
cross_rules:
  repo_cooldown:
    capabilities: [surge_runner_dispatch]
    window_seconds: 300
"""
    )
    c = PolicyCache()
    c.load_from_yaml(str(p))
    assert c.current.version == 7
    assert "repo_cooldown" in c.current.cross_rules
    assert c.current.cross_rules["repo_cooldown"]["window_seconds"] == 300


def test_missing_cross_rules_block_yields_empty(tmp_path: Path):
    p = tmp_path / "policy.yaml"
    p.write_text("version: 1\n")
    c = PolicyCache()
    c.load_from_yaml(str(p))
    assert c.current.cross_rules == {}


def test_missing_file_yields_empty_cross_rules(tmp_path: Path):
    c = PolicyCache()
    c.load_from_yaml(str(tmp_path / "nonexistent.yaml"))
    assert c.current.cross_rules == {}
