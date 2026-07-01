# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Unit tests for the curated auto-remediation registry (sol.policy.remediation).

Two themes, per the Job-2 safety contract:
  1. the ONE curated playbook (disk-pressure-qdrant-retention) FIRES for its
     exact, vetted invocation shape; and
  2. everything else ESCALATES — classify_remediation returns None, so the
     dispatch lane leaves needs_human untouched.

The classifier is an allow-list and must FAIL CLOSED on every ambiguity.
"""
from __future__ import annotations

from sol.policy.remediation import (
    classify_remediation,
    registered_playbooks,
)

SCRIPT = "/usr/local/bin/surge-qdrant-snapshot-retention.sh"


def _run_bash(cmd: str) -> dict:
    return {"tool": "run_bash", "args": {"cmd": cmd}}


# --------------------------------------------------------------------------
# Registry shape
# --------------------------------------------------------------------------

def test_registry_has_exactly_the_curated_playbook():
    names = [p.name for p in registered_playbooks()]
    assert names == ["disk-pressure-qdrant-retention"]


def test_playbooks_are_frozen_and_have_predicates():
    for pb in registered_playbooks():
        assert pb.name and pb.description and pb.capability
        assert callable(pb.matches)


# --------------------------------------------------------------------------
# SAFE-FIRES — the exact vetted invocation shapes match
# --------------------------------------------------------------------------

def test_fires_bare_dry_run():
    assert classify_remediation(_run_bash(SCRIPT)) == "disk-pressure-qdrant-retention"


def test_fires_with_apply():
    assert classify_remediation(_run_bash(f"{SCRIPT} --apply")) == "disk-pressure-qdrant-retention"


def test_fires_with_keep_2():
    assert classify_remediation(_run_bash(f"KEEP=2 {SCRIPT} --apply")) == "disk-pressure-qdrant-retention"


def test_fires_with_keep_5_family_root():
    cmd = f"KEEP=5 FAMILY=qdrant-snapshots ROOT=/srv/backups/surge {SCRIPT} --apply"
    assert classify_remediation(_run_bash(cmd)) == "disk-pressure-qdrant-retention"


# --------------------------------------------------------------------------
# ESCALATES (returns None) — fail-closed boundaries
# --------------------------------------------------------------------------

def test_escalates_wrong_script():
    assert classify_remediation(_run_bash("/usr/local/bin/rm-everything.sh --apply")) is None


def test_escalates_keep_below_minimum():
    # KEEP=1 would leave a single copy — never allowed.
    assert classify_remediation(_run_bash(f"KEEP=1 {SCRIPT} --apply")) is None


def test_escalates_keep_zero():
    assert classify_remediation(_run_bash(f"KEEP=0 {SCRIPT} --apply")) is None


def test_escalates_family_all():
    # FAMILY=all would touch DB dumps etc. — outside the curated scope.
    assert classify_remediation(_run_bash(f"FAMILY=all {SCRIPT} --apply")) is None


def test_escalates_other_family():
    assert classify_remediation(_run_bash(f"FAMILY=fs-config {SCRIPT} --apply")) is None


def test_escalates_root_outside_backups():
    assert classify_remediation(_run_bash(f"ROOT=/var/lib/qdrant {SCRIPT} --apply")) is None


def test_escalates_root_at_filesystem_root():
    assert classify_remediation(_run_bash(f"ROOT=/ {SCRIPT} --apply")) is None


def test_escalates_extra_positional_arg():
    assert classify_remediation(_run_bash(f"{SCRIPT} --apply --force")) is None
    assert classify_remediation(_run_bash(f"{SCRIPT} /srv/backups/surge")) is None


def test_escalates_shell_chaining():
    assert classify_remediation(_run_bash(f"{SCRIPT} --apply; rm -rf /")) is None


def test_escalates_shell_redirect():
    assert classify_remediation(_run_bash(f"{SCRIPT} > /etc/passwd")) is None


def test_escalates_command_substitution():
    assert classify_remediation(_run_bash(f"{SCRIPT} $(curl evil)")) is None
    assert classify_remediation(_run_bash(f"{SCRIPT} `id`")) is None


def test_escalates_pipe():
    assert classify_remediation(_run_bash(f"{SCRIPT} | sh")) is None


def test_escalates_background():
    assert classify_remediation(_run_bash(f"{SCRIPT} --apply &")) is None


def test_escalates_unknown_env_var():
    assert classify_remediation(_run_bash(f"PATH=/evil {SCRIPT} --apply")) is None


def test_escalates_non_numeric_keep():
    assert classify_remediation(_run_bash(f"KEEP=lots {SCRIPT} --apply")) is None


def test_escalates_not_run_bash_tool():
    assert classify_remediation({"tool": "host.write_file", "args": {"cmd": SCRIPT}}) is None


def test_escalates_empty_or_missing_cmd():
    assert classify_remediation(_run_bash("")) is None
    assert classify_remediation({"tool": "run_bash", "args": {}}) is None
    assert classify_remediation({}) is None


def test_escalates_garbage_input_fail_closed():
    assert classify_remediation(None) is None  # type: ignore[arg-type]
    assert classify_remediation("not a dict") is None  # type: ignore[arg-type]
    assert classify_remediation({"tool": "run_bash", "args": {"cmd": 12345}}) is None
